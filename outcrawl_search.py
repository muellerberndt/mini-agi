"""Outcrawl web search over its REST API, using the standard library."""

import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ENDPOINT = "https://api.outcrawl.ai/v1/search"
USER_AGENT = "MiniAGI/OutcrawlSearch (+https://github.com/muellerberndt/mini-agi)"
TIMEOUT = 30
MAX_RESULTS = 5
MAX_RESPONSE_BYTES = 1024 * 1024


def search(query: str) -> str:
    """Return up to five results as title, URL and snippet blocks."""
    if not query.strip():
        raise ValueError("Search query must not be empty")
    api_key = os.getenv("OUTCRAWL_API_KEY", "").strip()
    if not api_key:
        raise ValueError("OUTCRAWL_API_KEY must be set to use SEARCH_PROVIDER=outcrawl")
    request = Request(ENDPOINT, data=json.dumps({"query": query, "limit": MAX_RESULTS}).encode(),
                      headers={"Content-Type": "application/json", "Accept": "application/json",
                               "Authorization": f"Bearer {api_key}",
                               "User-Agent": USER_AGENT},
                      method="POST")
    try:
        with urlopen(request, timeout=TIMEOUT) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as error:
        reasons = {401: "invalid OUTCRAWL_API_KEY", 402: "out of credits",
                   429: "rate limited"}
        reason = reasons.get(error.code, error.reason)
        raise RuntimeError(f"Outcrawl HTTP error {error.code}: {reason}") from error
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("Outcrawl response is too large")
    hits = json.loads(raw).get("hits")
    if not isinstance(hits, list):
        raise ValueError("Outcrawl response has no hits")
    results = [f"{hit.get('title') or hit['url']}\n{hit['url']}\n{hit.get('snippet') or ''}".strip()
               for hit in hits[:MAX_RESULTS] if isinstance(hit, dict) and hit.get("url")]
    return "\n\n".join(results) if results else "No results found."
