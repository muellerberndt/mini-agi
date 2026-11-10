"""SpecStream web search over its REST API, using the standard library."""

import json
import os
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ENDPOINT = "https://api.specstream.ai/v1/web-search"
USER_AGENT = "MiniAGI/SpecStreamSearch (+https://github.com/muellerberndt/mini-agi)"
TIMEOUT = 30
MAX_RESULTS = 5
MAX_RESPONSE_BYTES = 1024 * 1024


def search(query: str) -> str:
    """Return up to five results as title, URL, publish date and snippet blocks."""
    if not query.strip():
        raise ValueError("Search query must not be empty")
    api_key = os.getenv("SPECSTREAM_API_KEY", "").strip()
    if not api_key:
        raise ValueError("SPECSTREAM_API_KEY must be set to use SEARCH_PROVIDER=specstream")
    url = f"{ENDPOINT}?{urlencode({'q': query[:2000], 'num': MAX_RESULTS})}"
    request = Request(url, headers={"Accept": "application/json",
                                    "Authorization": f"Bearer {api_key}",
                                    "User-Agent": USER_AGENT},
                      method="GET")
    try:
        with urlopen(request, timeout=TIMEOUT) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as error:
        reasons = {401: "invalid SPECSTREAM_API_KEY", 402: "out of balance",
                   403: "over the key's spending limit", 503: "busy or rate limited"}
        reason = reasons.get(error.code, error.reason)
        raise RuntimeError(f"SpecStream HTTP error {error.code}: {reason}") from error
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("SpecStream response is too large")
    data = json.loads(raw).get("data")
    sources = data.get("sources") if isinstance(data, dict) else None
    if not isinstance(sources, list):
        raise ValueError("SpecStream response has no sources")
    results = []
    for source in sources[:MAX_RESULTS]:
        if not isinstance(source, dict) or not source.get("url"):
            continue
        lines = [source.get("title") or source["url"], source["url"]]
        if source.get("published"):
            lines.append(f"Published: {source['published']}")
        lines.append(source.get("snippet") or "")
        results.append("\n".join(lines).strip())
    return "\n\n".join(results) if results else "No results found."
