import xml.etree.ElementTree as ET
from html import unescape
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..toolbox import ToolBox


_BING_SEARCH_URL = "https://www.bing.com/search"
_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
}


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
    Search the web with Bing and return structured results.
    """
    query = query.strip()
    if not query:
        raise ValueError("Query must not be empty.")

    if limit < 1:
        raise ValueError("Limit must be greater than 0.")

    request = Request(_build_bing_search_url(query), headers=_DEFAULT_HEADERS)
    try:
        with urlopen(request, timeout=15) as response:
            payload = response.read().decode("utf-8")
    except Exception as exc:
        raise RuntimeError("Bing search request failed.") from exc

    try:
        results = _parse_bing_rss(payload, limit=limit)
    except ET.ParseError as exc:
        raise RuntimeError("Bing search returned an invalid RSS response.") from exc

    return {
        "engine": "bing",
        "query": query,
        "results": results,
    }


def register_search_tools(toolbox: ToolBox):
    toolbox.register(bing_search)