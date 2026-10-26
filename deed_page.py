"""Optional publishing of one HTML file to a public deed.page URL over MCP Streamable HTTP.

deed.page (https://deed.page) is keyless: the first publish returns the page URL and an
owner token that can later update or delete the page. Uses only the standard library.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ENDPOINT = "https://deed.page/mcp"
USER_AGENT = "MiniAGI/DeedPage (+https://github.com/muellerberndt/mini-agi)"
PROTOCOL_VERSION = "2025-03-26"
TIMEOUT = 30
MAX_PAGE_BYTES = 1024 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024


def _decode(response, request_id):
    """Read a JSON or SSE reply and return this request's JSON-RPC message."""
    if response.headers.get_content_type() == "text/event-stream":
        data = []
        size = 0
        for line in response:
            size += len(line)
            if size > MAX_RESPONSE_BYTES:
                raise ValueError("deed.page response is too large")
            line = line.decode("utf-8").rstrip("\r\n")
            if line.startswith("data:"):
                data.append(line[5:].lstrip(" "))
            elif not line and data:
                message = json.loads("\n".join(data))
                data = []
                if message.get("id") == request_id:
                    return message
        raise ValueError("deed.page stream ended without a response")
    raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("deed.page response is too large")
    return json.loads(raw)


def _call_tool(name: str, arguments: dict) -> dict:
    """Initialize an MCP session, call one tool and return its structured result."""
    headers = {"Content-Type": "application/json",
               "Accept": "application/json, text/event-stream", "User-Agent": USER_AGENT}

    def post(method, params=None, request_id=None):
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        if request_id is not None:
            message["id"] = request_id
        request = Request(ENDPOINT, data=json.dumps(message).encode("utf-8"),
                          headers=headers, method="POST")
        try:
            with urlopen(request, timeout=TIMEOUT) as response:
                session = response.headers.get("Mcp-Session-Id")
                if request_id is None:
                    return None, session
                reply = _decode(response, request_id)
        except HTTPError as error:
            raise RuntimeError(f"deed.page HTTP error {error.code}: {error.reason}") from error
        if reply.get("jsonrpc") != "2.0" or reply.get("id") != request_id:
            raise ValueError("Invalid deed.page JSON-RPC response")
        if "error" in reply:
            raise RuntimeError(
                f"deed.page MCP error: {reply['error'].get('message', 'Unknown error')}")
        return reply.get("result") or {}, session

    _, session = post("initialize", {
        "protocolVersion": PROTOCOL_VERSION, "capabilities": {},
        "clientInfo": {"name": "miniagi", "version": "0.1.0"}}, 1)
    headers["MCP-Protocol-Version"] = PROTOCOL_VERSION
    if session:
        headers["Mcp-Session-Id"] = session
    post("notifications/initialized")
    result, _ = post("tools/call", {"name": name, "arguments": arguments}, 2)
    text = "\n".join(item["text"] for item in result.get("content", [])
                     if item.get("type") == "text" and isinstance(item.get("text"), str))
    if result.get("isError"):
        raise RuntimeError(f"deed.page {name} failed: {text or 'Unknown tool error'}")
    data = result.get("structuredContent")
    if data is None:
        try:
            data = json.loads(text)
        except ValueError as error:
            raise ValueError(f"deed.page {name} returned no result") from error
    return data


def publish(path: str, slug: str = None, ttl_seconds: int = None) -> dict:
    """Publish one HTML file as index.html. Returns url, slug and (first time) token."""
    page = Path(path.strip()).expanduser()
    if page.suffix.lower() not in (".html", ".htm"):
        raise ValueError("publish_page expects the path of an .html file")
    html = page.read_bytes()
    if len(html) > MAX_PAGE_BYTES:
        raise ValueError("Page is larger than 1 MB")
    arguments = {"files": {"index.html": html.decode("utf-8")}}
    if slug:
        arguments["slug"] = slug
    if ttl_seconds:
        arguments["ttl_seconds"] = int(ttl_seconds)
    return _call_tool("publish_site", arguments)


def delete(slug: str, token: str) -> dict:
    """Delete a page with the owner token from its first publish."""
    if not token:
        raise ValueError("Deleting a page needs its owner token (DEEDPAGE_TOKEN)")
    return _call_tool("delete_site", {"slug": slug, "token": token})


def main(argv=None):
    """Publish a file or delete a slug from the command line."""
    parser = argparse.ArgumentParser(description="Publish an HTML file to deed.page")
    parser.add_argument("file", nargs="?", help="HTML file to publish")
    parser.add_argument("--slug", help="Optional slug (subdomain)")
    parser.add_argument("--ttl", type=int, default=None, help="Expire after N seconds")
    parser.add_argument("--delete", metavar="SLUG",
                        help="Delete SLUG using DEEDPAGE_TOKEN from the environment")
    args = parser.parse_args(argv)
    if args.delete:
        token = os.getenv("DEEDPAGE_TOKEN")
        if not token:
            parser.error("--delete needs DEEDPAGE_TOKEN in the environment")
        print(json.dumps(delete(args.delete, token)))
        return 0
    if not args.file:
        parser.error("give an HTML file to publish, or --delete SLUG")
    result = publish(args.file, args.slug, args.ttl)
    print(f"Published (public): {result.get('url')}")
    if result.get("token"):
        print(f"Owner token for updates/deletes: {result['token']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
