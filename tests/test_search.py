"""Exercise provider selection and scripted agent actions without model API calls."""

# pylint: disable=protected-access,too-few-public-methods

import io
import json
import os
import runpy
from email.message import Message
from concurrent.futures import ThreadPoolExecutor
from unittest import TestCase, main
from unittest.mock import patch
from pathlib import Path
from urllib.error import HTTPError

from miniagi import MiniAGI
import parallel_search
import outcrawl_search


class Response(io.BytesIO):
    """A wire response with real MIME headers."""

    def __init__(self, body=b"", content_type="application/json", session=None):
        super().__init__(body)
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        if session:
            self.headers["Mcp-Session-Id"] = session


class Brain:
    """Scripted model and memory; no generated or live model responses."""

    def __init__(self, **_kwargs):
        self.model_name = "fixture"
        self.memory = []
        self.actions = []

    def predict(self, **_kwargs):
        """Return the next explicitly scripted action."""
        return self.actions.pop(0)

    def remember(self, **_kwargs):
        """Return observations from previous actions."""
        return self.memory

    def memorize(self, memory):
        """Retain the actual runtime observation."""
        self.memory.append(memory)

    def summarize(self, text, *_args, **_kwargs):
        """Keep short fixture text intact."""
        return text


def make_agent(provider=None):
    """Construct a real agent while substituting only model and tokenizer services."""
    with patch("miniagi.ThinkGPT", Brain), \
            patch("miniagi.tiktoken.encoding_for_model") as encoding:
        encoding.return_value.encode.side_effect = list
        return MiniAGI("fixture", "fixture", "Find Python documentation", 10000, 10000,
                       search_provider=provider)


class SearchTests(TestCase):
    """Verify the normal dispatcher through observation consumption and MCP wire I/O."""

    def setUp(self):
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.requests = []
        self.failure = None
        self.sse = False
        self.text = "Python documentation: https://docs.python.org/3/\nLanguage reference"

    def transport(self, request, timeout):
        """Observe every outbound request, including destination and identification."""
        self.assertEqual(request.full_url, "https://search.parallel.ai/mcp")
        self.assertEqual(request.get_header("User-agent"), parallel_search.USER_AGENT)
        self.assertIsNone(request.get_header("Authorization"))
        self.assertIsNone(request.get_header("X-api-key"))
        if request.method == "DELETE":
            self.assertEqual(timeout, 5)
            self.assertEqual(request.get_header("Mcp-session-id"), "transport-session")
            return Response()
        self.assertEqual(timeout, 30)
        message = json.loads(request.data)
        self.requests.append(message)
        if message["method"] == "initialize":
            self.assertEqual(request.get_header("Accept"), "application/json, text/event-stream")
            result = {"protocolVersion": "2025-03-26", "capabilities": {}}
            return Response(json.dumps({"jsonrpc": "2.0", "id": 1, "result": result}).encode(),
                            session="transport-session")
        self.assertEqual(request.get_header("Mcp-session-id"), "transport-session")
        self.assertEqual(request.get_header("Mcp-protocol-version"), "2025-03-26")
        if message["method"] == "notifications/initialized":
            self.assertNotIn("id", message)
            return Response()
        self.assertEqual(message["method"], "tools/call")
        self.assertEqual(message["params"]["name"], "web_search")
        if self.failure:
            raise self.failure
        result = {"content": [{"type": "text", "text": self.text}], "isError": False}
        message = {"jsonrpc": "2.0", "id": 2, "result": result}
        if self.sse:
            body = ': ping\n\ndata: {"jsonrpc":"2.0","method":"notification"}\n\n'
            body += "event: message\ndata: " + json.dumps(message) + "\n\n"
            return Response(body.encode(), "text/event-stream")
        return Response(json.dumps(message).encode())

    @staticmethod
    def act(agent, query="Python reference manual"):
        """Run think, action dispatch, and memory update through the actual agent."""
        agent.agent.actions.append(f"<r>Find a source.</r><c>web_search</c>\n{query}")
        agent.think()
        agent.act()
        return agent.agent.memory[-1]

    def test_unconfigured_and_explicit_duckduckgo(self):
        """The free incumbent remains selected and its first five results are preserved."""
        for provider in (None, "duckduckgo"):
            with self.subTest(provider=provider), patch("commands.DDGS") as ddgs, \
                    patch("parallel_search.urlopen") as network:
                ddgs.return_value.text.return_value = iter(range(8))
                memory = self.act(make_agent(provider))
                self.assertIn("[0, 1, 2, 3, 4]", memory)
                ddgs.return_value.text.assert_called_once_with("Python reference manual")
                network.assert_not_called()

    def test_env_choice_and_constructor_override(self):
        """Saved environment settings are read at agent creation; explicit choices win."""
        config = {"SEARCH_PROVIDER": "parallel", "PARALLEL_API_KEY": "unused"}
        with patch.dict(os.environ, config), \
                patch("parallel_search.urlopen", side_effect=self.transport), \
                patch("commands.DDGS") as ddgs:
            agent = make_agent()
            os.environ["SEARCH_PROVIDER"] = "none"
            self.assertIn(self.text, self.act(agent))
            self.assertIn("disabled", self.act(make_agent("none")))
            ddgs.assert_not_called()
        call = self.requests[-1]["params"]["arguments"]
        self.assertEqual(call["objective"], "Python reference manual")
        self.assertEqual(call["search_queries"], ["Python reference manual"])
        self.assertEqual(call["session_id"], agent.search_session_id)

    def test_disabled_and_unknown_never_contact_provider(self):
        """Disabled and invalid selections cannot silently fall back."""
        with patch("parallel_search.urlopen") as network, patch("commands.DDGS") as ddgs:
            self.assertIn("disabled", self.act(make_agent("none")))
            self.assertIn("must be", self.act(make_agent("typo")))
            network.assert_not_called()
            ddgs.assert_not_called()

    def test_json_and_sse_results_reach_memory(self):
        """Both supported response formats preserve source URLs and excerpts."""
        for self.sse in (False, True):
            with self.subTest(sse=self.sse), \
                    patch("parallel_search.urlopen", side_effect=self.transport):
                self.assertIn(self.text, self.act(make_agent("parallel")))

    def test_conversations_and_followups_keep_independent_ids(self):
        """Interleaved and concurrent objectives own separate stable research identities."""
        first, second = make_agent("parallel"), make_agent("parallel")
        self.assertNotEqual(first.search_session_id, second.search_session_id)
        with patch("parallel_search.urlopen", side_effect=self.transport):
            for agent in (first, second, first, second):
                self.act(agent)
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(self.act, (first, second)))
        ids = [m["params"]["arguments"]["session_id"] for m in self.requests
               if m["method"] == "tools/call"]
        self.assertEqual(ids[:4], [first.search_session_id, second.search_session_id] * 2)
        self.assertCountEqual(ids[4:], [first.search_session_id, second.search_session_id])
        self.assertNotIn(make_agent("parallel").search_session_id, ids)

    def test_errors_timeouts_and_retry_keep_identity(self):
        """Failures become observations; a later agent retry keeps its conversation ID."""
        for failure in (TimeoutError("timed out"), HTTPError(
                parallel_search.ENDPOINT, 429, "Too Many Requests", {}, None)):
            with self.subTest(failure=failure), \
                    patch("parallel_search.urlopen", side_effect=self.transport), \
                    patch("commands.DDGS") as ddgs:
                agent = make_agent("parallel")
                self.failure = failure
                self.assertIn("Command returned an error", self.act(agent))
                self.failure = None
                self.assertIn(self.text, self.act(agent))
                ids = [m["params"]["arguments"]["session_id"] for m in self.requests[-6:]
                       if m["method"] == "tools/call"]
                self.assertEqual(ids, [agent.search_session_id] * 2)
                ddgs.assert_not_called()

    def test_cancellation_propagates(self):
        """Ctrl-C aborts instead of becoming an observation or triggering a fallback."""
        self.failure = KeyboardInterrupt()
        with patch("parallel_search.urlopen", side_effect=self.transport), \
                patch("commands.DDGS") as ddgs:
            agent = make_agent("parallel")
            with self.assertRaises(KeyboardInterrupt):
                self.act(agent)
            self.assertEqual(agent.agent.memory, [])
            ddgs.assert_not_called()

    def test_cli_confirmation_can_abort_search(self):
        """The advertised CLI confirmation gate blocks the outbound action."""
        def model(**kwargs):
            brain = Brain(**kwargs)
            brain.actions = ["<r>Find sources.</r><c>web_search</c>\nPython documentation",
                             "<r>Stopped.</r><c>done</c>\n"]
            return brain

        config = {"SEARCH_PROVIDER": "parallel", "PROMPT_USER": "true",
                  "MAX_CONTEXT_SIZE": "10000", "MAX_MEMORY_ITEM_SIZE": "10000",
                  "WORK_DIR": str(Path.cwd())}
        with patch.dict(os.environ, config), patch("thinkgpt.llm.ThinkGPT", model), \
                patch("tiktoken.encoding_for_model") as encoding, \
                patch("builtins.input", return_value="Skip this search") as confirmation, \
                patch("sys.argv", ["miniagi.py", "Find Python documentation"]), \
                patch("parallel_search.urlopen") as network, \
                patch("sys.stdout", new_callable=io.StringIO), \
                self.assertRaises(SystemExit):
            encoding.return_value.encode.side_effect = list
            runpy.run_path(str(Path(__file__).resolve().parents[1] / "miniagi.py"),
                           run_name="__main__")
        confirmation.assert_called_once()
        network.assert_not_called()

    def test_invalid_query_never_contacts_service(self):
        """Reject empty searches locally."""
        with patch("parallel_search.urlopen") as network:
            self.assertIn("must not be empty", self.act(make_agent("parallel"), "  "))
            network.assert_not_called()

    def test_tool_error_and_malformed_responses(self):
        """Server failures and invalid payloads remain visible to the agent."""
        original = self.transport

        def broken(request, timeout):
            if request.data and json.loads(request.data)["method"] == "tools/call":
                return Response(payload)
            return original(request, timeout)

        for payload in (
                b'{"jsonrpc":"2.0","id":2,"result":{"isError":true,"content":'
                b'[{"type":"text","text":"Free anonymous quota exceeded"}]}}',
                b'{"jsonrpc":"2.0","id":2,"error":{"message":"Service unavailable"}}',
                b'{"jsonrpc":"2.0","id":2,"result":{"content":[]}}',
                b'{"jsonrpc":"2.0","id":99,"result":{}}', b'invalid json'):
            with self.subTest(payload=payload), \
                    patch("parallel_search.urlopen", side_effect=broken):
                self.assertIn("Command returned an error", self.act(make_agent("parallel")))


class OutcrawlSearchTests(TestCase):
    """Verify the Outcrawl provider through the agent's dispatcher and REST wire I/O."""

    def setUp(self):
        self.environment = patch.dict(os.environ, {"OUTCRAWL_API_KEY": " outcrawl-key "},
                                      clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.requests = []
        self.failure = None
        self.body = {"hits": [
            {"url": "https://docs.python.org/3/", "title": "Python documentation",
             "snippet": "Language reference", "rank": 1},
            {"title": "no url", "snippet": "dropped", "rank": 2},
            {"url": "https://peps.python.org/", "rank": 3},
        ], "usage": {"credits": "1.5"}}

    def transport(self, request, timeout):
        """Observe the outbound request: destination, identification, key and body."""
        self.assertEqual(request.full_url, "https://api.outcrawl.ai/v1/search")
        self.assertEqual(request.method, "POST")
        self.assertEqual(timeout, 30)
        self.assertEqual(request.get_header("User-agent"), outcrawl_search.USER_AGENT)
        self.assertEqual(request.get_header("Authorization"), "Bearer outcrawl-key")
        self.requests.append(json.loads(request.data))
        if self.failure:
            raise self.failure
        return Response(json.dumps(self.body).encode())

    def test_results_reach_memory(self):
        """Hits with a URL become title, URL and snippet blocks; nothing falls back."""
        with patch("outcrawl_search.urlopen", side_effect=self.transport), \
                patch("parallel_search.urlopen") as parallel, patch("commands.DDGS") as ddgs:
            memory = SearchTests.act(make_agent("outcrawl"))
            parallel.assert_not_called()
            ddgs.assert_not_called()
        self.assertEqual(self.requests, [{"query": "Python reference manual", "limit": 5}])
        self.assertIn("Python documentation\nhttps://docs.python.org/3/\nLanguage reference",
                      memory)
        self.assertIn("https://peps.python.org/\nhttps://peps.python.org/", memory)
        self.assertNotIn("dropped", memory)

    def test_env_choice(self):
        """SEARCH_PROVIDER=outcrawl selects Outcrawl at agent creation."""
        with patch.dict(os.environ, {"SEARCH_PROVIDER": "outcrawl"}), \
                patch("outcrawl_search.urlopen", side_effect=self.transport):
            self.assertIn("Python documentation", SearchTests.act(make_agent()))
        self.assertEqual(len(self.requests), 1)

    def test_missing_key_and_empty_query_never_contact_service(self):
        """Local validation runs before any request."""
        with patch("outcrawl_search.urlopen") as network:
            self.assertIn("must not be empty", SearchTests.act(make_agent("outcrawl"), "  "))
            for value in (None, "  "):
                with self.subTest(value=value), patch.dict(os.environ):
                    if value is None:
                        del os.environ["OUTCRAWL_API_KEY"]
                    else:
                        os.environ["OUTCRAWL_API_KEY"] = value
                    self.assertIn("OUTCRAWL_API_KEY must be set",
                                  SearchTests.act(make_agent("outcrawl")))
            network.assert_not_called()

    def test_http_errors_become_observations(self):
        """Key, credit and rate-limit failures reach the agent without switching providers."""
        for code, reason in ((401, "invalid OUTCRAWL_API_KEY"), (402, "out of credits"),
                             (429, "rate limited"), (500, "Internal Server Error")):
            self.failure = HTTPError(outcrawl_search.ENDPOINT, code, "Internal Server Error",
                                     {}, None)
            with self.subTest(code=code), \
                    patch("outcrawl_search.urlopen", side_effect=self.transport), \
                    patch("commands.DDGS") as ddgs:
                memory = SearchTests.act(make_agent("outcrawl"))
                self.assertIn("Command returned an error", memory)
                self.assertIn(f"Outcrawl HTTP error {code}: {reason}", memory)
                ddgs.assert_not_called()

    def test_malformed_and_empty_responses(self):
        """Invalid payloads are errors; an empty hit list is a normal observation."""
        for body, expected in ((b"invalid json", "Command returned an error"),
                               (b'{"error":"x"}', "Outcrawl response has no hits"),
                               (b"x" * (outcrawl_search.MAX_RESPONSE_BYTES + 1), "too large"),
                               (b'{"hits":[]}', "No results found.")):
            with self.subTest(body=body[:20]), \
                    patch("outcrawl_search.urlopen", return_value=Response(body)):
                self.assertIn(expected, SearchTests.act(make_agent("outcrawl")))

    def test_cancellation_propagates(self):
        """Ctrl-C aborts instead of becoming an observation."""
        self.failure = KeyboardInterrupt()
        with patch("outcrawl_search.urlopen", side_effect=self.transport):
            agent = make_agent("outcrawl")
            with self.assertRaises(KeyboardInterrupt):
                SearchTests.act(agent)
            self.assertEqual(agent.agent.memory, [])


if __name__ == "__main__":
    main()
