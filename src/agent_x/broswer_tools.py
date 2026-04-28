from urllib.parse import urlparse
import html_to_markdown
import rich

from playwright.sync_api import sync_playwright

from .g import global_context

def _derive_asset_name(url: str, fallback: str, extension: str) -> str:
    path = urlparse(url).path.rstrip("/")
    name = path.split("/")[-1] if path else ""
    if not name:
        name = fallback
    if "." not in name:
        name = f"{name}{extension}"
    return name


def _store_asset(bucket: dict[str, str], name: str, content: str) -> None:
    if name not in bucket:
        bucket[name] = content
        return

    stem, dot, suffix = name.partition(".")
    index = 2
    while True:
        candidate = f"{stem}_{index}"
        if dot:
            candidate = f"{candidate}.{suffix}"
        if candidate not in bucket:
            bucket[candidate] = content
            return
        index += 1

def _check_playwright():
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
            browser.close()
        except Exception as e:
            raise RuntimeError("Playwright is installed but cannot be used. Please check your Playwright installation and ensure that the necessary browsers are installed.") from e

class Browser:
    def __init__(self):
        _check_playwright()

    def _new_page(self, browser):
        page = browser.new_page()
        page.set_default_timeout(15000)
        return page

    def take_screenshot(
        self, 
        url: str, 
        full_page = False
        ) -> bytes:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = self._new_page(browser)
            page.goto(url, wait_until="networkidle")
            screenshot = page.screenshot(full_page=full_page)
            browser.close()
            return screenshot
    
    def get_page_html(self, url: str) -> str:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = self._new_page(browser)
            page.goto(url, wait_until="networkidle")
            content = page.content()
            browser.close()
            return content
    
    def broswer_get_page(self, url: str) -> str:
        """
        Get the rendered HTML content of a web page and return it as markdown. 
        """
        html = self.get_page_html(url)
        r = html_to_markdown.convert(html)
        assert r.content, "Failed to convert HTML to markdown."
        return r.content
    
def register_browser_tools():
    mcp = global_context().mcp
    try:
        browser = Browser()
    except Exception as e:
        rich.print(f"[bold red]Failed to initialize browser tools (skipped):[/bold red] {e}.")
        return
    mcp.tool()(browser.broswer_get_page)
