"""Exercise the opt-in publish_page command without model API calls or network access."""

# pylint: disable=wrong-import-order

import io
import json
import os
import shutil
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from email.message import Message
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import patch

import deed_page
import miniagi
from test_search import make_agent


class Response(io.BytesIO):
    """A wire response with real MIME headers."""

    def __init__(self, body=b"", content_type="application/json"):
        super().__init__(body)
        self.headers = Message()
        self.headers["Content-Type"] = content_type


class DeedPageTests(TestCase):
    """Verify prompt gating, the agent dispatch path and the MCP wire messages."""

    def setUp(self):
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.calls = []
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder)
        self.page = Path(folder) / "report.html"
        self.page.write_text("<!doctype html><h1>Report</h1>", encoding="utf-8")

    def transport(self, request, timeout):
        """Observe each outbound request and answer like the deed.page MCP server."""
        self.assertEqual(request.full_url, "https://deed.page/mcp")
        self.assertEqual(request.get_header("User-agent"), deed_page.USER_AGENT)
        self.assertEqual(timeout, 30)
        message = json.loads(request.data)
        if message["method"] == "initialize":
            result = {"protocolVersion": "2025-03-26", "capabilities": {}}
            return Response(json.dumps({"jsonrpc": "2.0", "id": 1, "result": result}).encode())
        if message["method"] == "notifications/initialized":
            return Response()
        self.calls.append(message["params"])
        name = message["params"]["name"]
        data = {"url": "https://quiet-fox.deed.page/", "slug": "quiet-fox",
                "token": "deed_tok_fixture"} if name == "publish_site" else \
            {"ok": True, "deleted": message["params"]["arguments"]["slug"]}
        result = {"content": [{"type": "text", "text": json.dumps(data)}],
                  "structuredContent": data, "isError": False}
        body = "event: message\ndata: " + json.dumps(
            {"jsonrpc": "2.0", "id": 2, "result": result}) + "\n\n"
        return Response(body.encode(), "text/event-stream")

    def act(self, arg):
        """Run think, dispatch and memory update through the actual agent."""
        agent = make_agent()
        agent.agent.actions.append(f"<r>Share the report.</r><c>publish_page</c>\n{arg}")
        agent.think()
        out = io.StringIO()
        with redirect_stdout(out):
            agent.act()
        return agent.agent.memory[-1], out.getvalue()

    def test_command_is_listed_only_when_enabled(self):
        """The prompt is unchanged unless DEEDPAGE_PUBLISH is set."""
        self.assertEqual(miniagi.command_prompt(), miniagi.PROMPT)
        self.assertNotIn("publish_page", miniagi.PROMPT)
        os.environ["DEEDPAGE_PUBLISH"] = "true"
        self.assertIn("publish_page | path to an HTML file", miniagi.command_prompt())

    def test_disabled_never_contacts_service(self):
        """Without opt-in the command reports that it is disabled."""
        with patch("deed_page.urlopen") as network:
            memory, _ = self.act(str(self.page))
        self.assertIn("disabled", memory)
        network.assert_not_called()

    def test_publish_keeps_token_out_of_memory(self):
        """The URL reaches the agent; the owner token is only printed for the user."""
        os.environ.update({"DEEDPAGE_PUBLISH": "true", "DEEDPAGE_TTL": "600"})
        with patch("deed_page.urlopen", side_effect=self.transport):
            memory, printed = self.act(str(self.page))
        self.assertIn("https://quiet-fox.deed.page/", memory)
        self.assertNotIn("deed_tok_fixture", memory)
        self.assertIn("deed_tok_fixture", printed)
        call = self.calls[-1]
        self.assertEqual(call["name"], "publish_site")
        self.assertEqual(call["arguments"]["files"],
                         {"index.html": "<!doctype html><h1>Report</h1>"})
        self.assertEqual(call["arguments"]["ttl_seconds"], 600)

    def test_rejects_non_html_and_reports_tool_errors(self):
        """Bad input and server errors stay visible to the agent."""
        os.environ["DEEDPAGE_PUBLISH"] = "true"
        with patch("deed_page.urlopen") as network:
            memory, _ = self.act("notes.txt")
        self.assertIn("Command returned an error", memory)
        network.assert_not_called()

        def failing(request, timeout):
            if json.loads(request.data)["method"] == "tools/call":
                return Response(b'{"jsonrpc":"2.0","id":2,"result":{"isError":true,'
                                b'"content":[{"type":"text","text":"slug_taken"}]}}')
            return self.transport(request, timeout)

        with patch("deed_page.urlopen", side_effect=failing):
            memory, _ = self.act(str(self.page))
        self.assertIn("slug_taken", memory)

    def test_cli_delete_needs_token(self):
        """--delete uses DEEDPAGE_TOKEN and refuses to run without it."""
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            deed_page.main(["--delete", "quiet-fox"])
        os.environ["DEEDPAGE_TOKEN"] = "deed_tok_fixture"
        with patch("deed_page.urlopen", side_effect=self.transport), \
                redirect_stdout(io.StringIO()) as out:
            deed_page.main(["--delete", "quiet-fox"])
        self.assertIn('"deleted": "quiet-fox"', out.getvalue())
        self.assertEqual(self.calls[-1]["arguments"],
                         {"slug": "quiet-fox", "token": "deed_tok_fixture"})


if __name__ == "__main__":
    main()
