import ssl
import xml.etree.ElementTree as ET
from html import unescape
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from playwright.sync_api import sync_playwright

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


def _browser_bing_search(query: str, bing_url: str, limit: int, timeout_ms: int) -> dict[str, Any]:
    """Use a headless browser to search bing.com and parse results from the rendered page."""
    playwright = sync_playwright().start()
    try:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        page.set_default_timeout(timeout_ms)

        # Navigate to Bing search results page
        search_url = f"{bing_url}/search?q={urlencode({'q': query})}"
        page.goto(search_url, wait_until="domcontentloaded")

        # Wait for results to appear
        try:
            page.wait_for_selector("#b_results", timeout=10000)
        except Exception:
            pass  # Continue anyway, we'll parse what we can

        # Parse search results from the page
        results_data = page.evaluate("""() => {
            const results = [];
            const elements = document.querySelectorAll('#b_results .b_algo');
            for (const el of elements) {
                const titleEl = el.querySelector('h2 a');
                const snippetEl = el.querySelector('.b_caption p');
                const title = titleEl ? titleEl.textContent : '';
                const link = titleEl ? titleEl.href : '';
                const snippet = snippetEl ? snippetEl.textContent : '';
                if (title && link) {
                    results.push({ title, link, snippet });
                }
            }
            return results;
        }""")

        context.close()
        browser.close()
    finally:
        playwright.stop()

    # Build structured results
    results = []
    for item in results_data[:limit]:
        results.append(
            {
                "title": item.get("title", "").strip(),
                "link": item.get("link", "").strip(),
                "snippet": item.get("snippet", "").strip(),
                "published_at": "",
            }
        )

    return {
        "engine": "bing",
        "method": "browser",
        "query": query,
        "results": results,
    }


def browser_bing_search(query: str, limit: int = 10, bing_url: str = "https://www.bing.com", timeout_ms: int = 30000) -> dict[str, Any]:
    """
    Search the web using a headless browser to browse bing.com directly.
    This is more reliable than the RSS-based bing_search, especially in regions where the RSS feed is unstable.
    Go to the source link for the results if you need more details or context.
    Use `bing_url` to switch between global bing.com (default) or regional versions like bing.cn for China.
    """
    query = query.strip()
    if not query:
        raise ValueError("Query must not be empty.")

    if limit < 1:
        raise ValueError("Limit must be greater than 0.")

    try:
        return _browser_bing_search(query, bing_url, limit, timeout_ms)
    except Exception as exc:
        raise RuntimeError(f"Browser Bing search failed: {exc}") from exc


def expose_search_tools() -> list[Callable]:
    return [bing_search, browser_bing_search]
