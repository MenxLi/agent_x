import html_to_markdown
import rich
from playwright.sync_api import sync_playwright

from ..toolbox import ToolBox


def _check_playwright():
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
            browser.close()
        except Exception as e:
            raise 

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
        full_page=False,
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

    def browser_get_page(self, url: str) -> str:
        """
        Get the rendered HTML content of a web page and return it as markdown.
        """
        html = self.get_page_html(url)
        r = html_to_markdown.convert(html)
        assert r.content, "Failed to convert HTML to markdown."
        return r.content


def register_browser_tools(toolbox: ToolBox):
    try:
        browser = Browser()
    except Exception as e:
        rich.print(f"[bold red]Failed to initialize browser tools (skipped):[/bold red] {e}.")
        return
    toolbox.register(browser.browser_get_page)