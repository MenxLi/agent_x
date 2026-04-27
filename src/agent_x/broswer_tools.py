from urllib.parse import urlparse

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

    def render_page(self, url: str) -> dict[str, dict[str, str]]:
        """
        Render the page and capture HTML, CSS, and JS assets.
        Returns a dictionary with keys "html", "css", and "js", each containing a mapping of asset names to their content.
        """
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = self._new_page(browser)

            assets: dict[str, dict[str, str]] = {
                "html": {},
                "css": {},
                "js": {},
            }

            def on_response(response):
                resource_type = response.request.resource_type
                if resource_type not in {"stylesheet", "script"}:
                    return

                try:
                    content = response.text()
                except Exception:
                    return

                if not content:
                    return

                if resource_type == "stylesheet":
                    name = _derive_asset_name(response.url, "styles", ".css")
                    _store_asset(assets["css"], name, content)
                    return

                name = _derive_asset_name(response.url, "script", ".js")
                _store_asset(assets["js"], name, content)

            page.on("response", on_response)
            page.goto(url, wait_until="networkidle")
            _store_asset(assets["html"], _derive_asset_name(page.url, "index", ".html"), page.content())

            browser.close()
            return assets
    
def register_browser_tools():
    mcp = global_context().mcp
    browser = Browser()
    mcp.tool()(browser.render_page)
