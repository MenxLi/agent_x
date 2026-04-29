from collections.abc import Callable
from typing import Literal, TypeVar
import functools, time

import html_to_markdown
from playwright.sync_api import Browser as PlaywrightBrowser
from playwright.sync_api import BrowserContext, Page
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Playwright, sync_playwright

from ..toolbox import ToolBox


WaitUntil = Literal["commit", "domcontentloaded", "load", "networkidle"]
PageResult = TypeVar("PageResult")


def _slice_content(content: str, start_char: int, max_chars: int) -> str:
    page_content = content[start_char:start_char + max_chars]

    if start_char > 0 or start_char + max_chars < len(content):
        page_content += "\n\n[Content truncated due to length limits...]"

    return page_content

def _get_ttl_hash():
    # https://stackoverflow.com/a/55900800
    return round(time.time() / 3600)

class Browser:
    def _with_page(self, timeout_ms: int, action: Callable[[Page], PageResult]) -> PageResult:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context()

            try:
                return self._run_with_context(context, timeout_ms, action)
            finally:
                context.close()
                browser.close()

    def _run_with_context(
        self,
        context: BrowserContext,
        timeout_ms: int,
        action: Callable[[Page], PageResult],
    ) -> PageResult:
        page = context.new_page()
        page.set_default_timeout(timeout_ms)

        try:
            return action(page)
        finally:
            page.close()

    def take_screenshot(
        self,
        url: str,
        full_page=False,
        wait_until: WaitUntil = "domcontentloaded",
        timeout_ms: int = 15000,
    ) -> bytes:
        def _capture(page):
            page.goto(url, wait_until=wait_until)
            return page.screenshot(full_page=full_page)

        return self._with_page(timeout_ms, _capture)

    @functools.lru_cache(maxsize=32)
    def get_page_html(
        self,
        url: str,
        wait_until: WaitUntil = "domcontentloaded",
        timeout_ms: int = 15000,
        ttl_hash: str | int | None = None,
    ) -> str:
        del ttl_hash
        def _load(page):
            page.goto(url, wait_until=wait_until)
            return page.content()

        return self._with_page(timeout_ms, _load)

    def browser_get_page(
        self,
        url: str,
        start_char: int = 0,
        max_chars: int = 100000,
        wait_until: WaitUntil = "domcontentloaded",
        timeout_ms: int = 15000,
    ) -> str:
        """
        Get the rendered HTML content of a web page and return it as markdown.
        """
        if start_char < 0:
            raise ValueError("start_char must be greater than or equal to 0.")

        if max_chars < 1:
            raise ValueError("max_chars must be greater than 0.")

        html = self.get_page_html(url, wait_until=wait_until, timeout_ms=timeout_ms, ttl_hash=_get_ttl_hash())
        r = html_to_markdown.convert(html)
        if not r.content:
            raise RuntimeError("Failed to convert HTML to markdown.")

        return _slice_content(r.content, start_char, max_chars)


def register_browser_tools(toolbox: ToolBox):
    browser = Browser()
    toolbox.register(browser.browser_get_page)