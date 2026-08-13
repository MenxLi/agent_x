from typing import Callable
from playwright.sync_api import sync_playwright


def _safe_text(selector) -> str:
    """Safely extract inner text from a selector, returning empty string if not found."""
    if selector is None:
        return ""
    return selector.inner_text().strip()


def _safe_attr(selector, attr: str) -> str:
    """Safely get an attribute from a selector, returning empty string if not found."""
    if selector is None:
        return ""
    value = selector.get_attribute(attr)
    return value.strip() if value else ""


def _extract_snippet(algo) -> str:
    """Try multiple selectors to extract the snippet text."""
    candidates = [
        ".b_caption p",
        ".b_algo .b_line",
        ".b_algo .b_ans",
        ".b_algo .b_visit",
    ]
    for selector in candidates:
        el = algo.query_selector(selector)
        text = _safe_text(el)
        if text:
            return text
    return ""


def bing_search(query: str, limit: int = 10, bing_url: str = "https://www.bing.com", timeout_ms: int = 30000) -> list[dict]:
    """
    Search the web using a headless browser to browse bing.com directly.
    Args:
        query (str): The search query.
        limit (int): The maximum number of search results to return. Default is 10.
        bing_url (str): The URL of the Bing search engine. Default is "https://www.bing.com".
        timeout_ms (int): The maximum time to wait for the page to load and for elements to appear, milliseconds. Default is 30000.
    Returns:
        list[dict]: A list of dictionaries containing the search results, each with 'title', 'link', and 'snippet' keys.
    """
    query = query.strip()
    if not query:
        raise ValueError("Query must not be empty.")

    if limit < 1:
        raise ValueError("Limit must be greater than 0.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(bing_url, timeout=timeout_ms)
        page.fill("input[name='q']", query)
        page.keyboard.press("Enter")
        page.wait_for_selector("#b_results", timeout=timeout_ms)

        results = []
        # Iterate through all li.b_algo elements, not by nth-child index
        algos = page.query_selector_all("#b_results > li.b_algo")
        for algo in algos:
            if len(results) >= limit:
                break

            # Extract title
            title_el = algo.query_selector("h2")
            title = _safe_text(title_el)
            if not title:
                # Skip results with no title (likely non-organic)
                continue

            # Extract link
            link_el = algo.query_selector("h2 a")
            link = _safe_attr(link_el, "href")

            # Extract snippet with fallback selectors
            snippet = _extract_snippet(algo)

            results.append({"title": title, "link": link, "snippet": snippet})

        browser.close()

    return results


def expose_search_tools() -> list[Callable]:
    return [bing_search]


if __name__ == "__main__":
    query = input("Enter your search query: ")
    results = bing_search(query, 10)
    for idx, result in enumerate(results):
        print(f"Result {idx + 1}:")
        print(f"Title: {result['title']}")
        print(f"Link: {result['link']}")
        print(f"Snippet: {result['snippet']}\n")
