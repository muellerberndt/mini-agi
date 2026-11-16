"""Keenable web search over its REST API, using the standard library."""

import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen


PUBLIC_ENDPOINT = "https://api.keenable.ai/v1/search/public"
KEYED_ENDPOINT = "https://api.keenable.ai/v1/search"
APP_TITLE = "MiniAGI"
USER_AGENT = "MiniAGI/KeenableSearch (+https://github.com/muellerberndt/mini-agi)"
TIMEOUT = 30
MAX_RESULTS = 5
SNIPPET_MAX_LENGTH = 500
MAX_RESPONSE_BYTES = 1024 * 1024


def search(query: str) -> str:
    """Return up to five results as title, URL and snippet blocks.

    Without KEENABLE_API_KEY the keyless public endpoint is used (rate limited per IP);
    with a key the keyed endpoint is used.
    """
    if not query.strip():
        raise ValueError("Search query must not be empty")
    api_key = os.getenv("KEENABLE_API_KEY", "").strip()
    headers = {"Content-Type": "application/json", "Accept": "application/json",
               "User-Agent": USER_AGENT}
    if api_key:
        endpoint = KEYED_ENDPOINT
        headers["X-API-Key"] = api_key
    else:
        endpoint = PUBLIC_ENDPOINT
        headers["X-Keenable-Title"] = APP_TITLE
    body = {"query": query, "max_results": MAX_RESULTS,
            "snippet_max_length": SNIPPET_MAX_LENGTH}
    request = Request(endpoint, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urlopen(request, timeout=TIMEOUT) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as error:
        reasons = {401: "invalid KEENABLE_API_KEY", 402: "out of credits",
                   429: "rate limited"}
        reason = reasons.get(error.code, error.reason)
        raise RuntimeError(f"Keenable HTTP error {error.code}: {reason}") from error
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("Keenable response is too large")
    results = json.loads(raw).get("results")
    if not isinstance(results, list):
        raise ValueError("Keenable response has no results")
    blocks = [f"{hit.get('title') or hit['url']}\n{hit['url']}\n{hit.get('snippet') or ''}".strip()
              for hit in results[:MAX_RESULTS] if isinstance(hit, dict) and hit.get("url")]
    return "\n\n".join(blocks) if blocks else "No results found."
