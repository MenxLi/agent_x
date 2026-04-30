import ssl
import xml.etree.ElementTree as ET
from html import unescape
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

_BING_SEARCH_URL = "https://www.bing.com/search"
_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
}

# Create SSL context with proper CA certificates
try:
    import certifi
    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CONTEXT = ssl.create_default_context()


def _build_bing_search_url(query: str) -> str:
    return f"{_BING_SEARCH_URL}?{urlencode({'format': 'rss', 'q': query})}"


def _parse_bing_rss(payload: str, limit: int) -> list[dict[str, str]]:
    root = ET.fromstring(payload)
    items = root.findall("./channel/item")

    results: list[dict[str, str]] = []
    for item in items[:limit]:
        results.append(
            {
                "title": unescape(item.findtext("title", default="").strip()),
                "link": item.findtext("link", default="").strip(),
                "snippet": unescape(item.findtext("description", default="").strip()),
                "published_at": item.findtext("pubDate", default="").strip(),
            }
        )
    return results


def bing_search(query: str, limit: int = 10) -> dict[str, Any]:
    """
    Search the web with Bing and return structured results using the RSS feed.
    Go to the source link for the results if you need more details or context, as the returned snippets may be brief.
    [May not be very reliable in some cases]
    """
    query = query.strip()
    if not query:
        raise ValueError("Query must not be empty.")

    if limit < 1:
        raise ValueError("Limit must be greater than 0.")

    request = Request(_build_bing_search_url(query), headers=_DEFAULT_HEADERS)
    try:
        with urlopen(request, timeout=15, context=_SSL_CONTEXT) as response:
            payload = response.read().decode("utf-8")
    except Exception as exc:
        raise RuntimeError(f"Bing search request failed: {exc}") from exc

    try:
        results = _parse_bing_rss(payload, limit=limit)
    except ET.ParseError as exc:
        raise RuntimeError("Bing search returned an invalid RSS response.") from exc

    return {
        "engine": "bing",
        "query": query,
        "results": results,
    }

def expose_search_tools() -> list[Callable]:
    return [bing_search]
