"""Anonymous Parallel Search over MCP Streamable HTTP, using the standard library."""

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4


ENDPOINT = "https://search.parallel.ai/mcp"
USER_AGENT = "MiniAGI/ParallelSearch (+https://github.com/muellerberndt/mini-agi)"
PROTOCOL_VERSION = "2025-03-26"
TIMEOUT = 30
MAX_RESPONSE_BYTES = 1024 * 1024


def _decode_response(response, request_id):
    """Read either JSON or SSE, stopping at this request's JSON-RPC response."""
    if response.headers.get_content_type() == "text/event-stream":
        data = []
        size = 0
        for line in response:
            size += len(line)
            if size > MAX_RESPONSE_BYTES:
                raise ValueError("Parallel response is too large")
            line = line.decode("utf-8").rstrip("\r\n")
            if line.startswith("data:"):
                data.append(line[5:].lstrip(" "))
            elif not line and data:
                message = json.loads("\n".join(data))
                data = []
                if message.get("id") == request_id:
                    return message
        raise ValueError("Parallel stream ended without a response")
    raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("Parallel response is too large")
    return json.loads(raw)


def _post(headers, method, params=None, request_id=None):
    """Send a single MCP message and validate its JSON-RPC response."""
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
            result = _decode_response(response, request_id)
    except HTTPError as error:
        raise RuntimeError(f"Parallel HTTP error {error.code}: {error.reason}") from error
    if result.get("jsonrpc") != "2.0" or result.get("id") != request_id:
        raise ValueError("Invalid Parallel JSON-RPC response")
    if "error" in result:
        raise RuntimeError(f"Parallel MCP error: {result['error'].get('message', 'Unknown error')}")
    if not isinstance(result.get("result"), dict):
        raise ValueError("Parallel MCP response has no result")
    return result["result"], session


def search(query: str, session_id: str = None) -> str:
    """Search with a conversation ID supplied by MiniAGI, or a new standalone run."""
    if not query.strip():
        raise ValueError("Search query must not be empty")
    headers = {"Content-Type": "application/json",
               "Accept": "application/json, text/event-stream", "User-Agent": USER_AGENT}
    initialized, transport_session = _post(headers, "initialize", {
        "protocolVersion": PROTOCOL_VERSION, "capabilities": {},
        "clientInfo": {"name": "miniagi", "version": "0.1.0"}}, 1)
    if initialized.get("protocolVersion") != PROTOCOL_VERSION:
        raise ValueError("Parallel selected an unsupported MCP protocol version")
    headers["MCP-Protocol-Version"] = PROTOCOL_VERSION
    if transport_session:
        headers["Mcp-Session-Id"] = transport_session
    try:
        _post(headers, "notifications/initialized")
        result, _ = _post(headers, "tools/call", {
            "name": "web_search", "arguments": {
                "objective": query, "search_queries": [query],
                "session_id": session_id if session_id is not None else str(uuid4())}}, 2)
        text = "\n".join(item["text"] for item in result.get("content", [])
                         if item.get("type") == "text" and isinstance(item.get("text"), str))
        if result.get("isError"):
            raise RuntimeError(f"Parallel search failed: {text or 'Unknown tool error'}")
        if not text:
            raise ValueError("Parallel search returned no text")
        return text
    finally:
        if transport_session:
            # Session cleanup must not hide a search error or interrupt cancellation.
            try:
                with urlopen(Request(ENDPOINT, headers=headers, method="DELETE"), timeout=5):
                    pass
            except (URLError, OSError):
                pass
