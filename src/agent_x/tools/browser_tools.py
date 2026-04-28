from contextlib import contextmanager
from threading import Condition, RLock
from typing import Literal

import html_to_markdown
from playwright.sync_api import Browser as PlaywrightBrowser
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Playwright, sync_playwright

from ..toolbox import ToolBox


WaitUntil = Literal["commit", "domcontentloaded", "load", "networkidle"]

class Browser:
    def __init__(self):
        self._lock = RLock()
        self._idle = Condition(self._lock)
        self._playwright: Playwright | None = None
        self._browser: PlaywrightBrowser | None = None
        self._active_requests = 0
        self._is_closing = False

    def _ensure_browser(self) -> PlaywrightBrowser:
        with self._idle:
            if self._is_closing:
                raise RuntimeError("Browser is closing.")
            if self._browser is None:
                try:
                    self._playwright = sync_playwright().start()
                    self._browser = self._playwright.chromium.launch()
                except PlaywrightError as exc:
                    if self._playwright is not None:
                        self._playwright.stop()
                        self._playwright = None
                    raise RuntimeError(
                        "Failed to launch Playwright Chromium. Install the browser binaries with 'playwright install chromium'."
                    ) from exc
            return self._browser

    def close(self) -> None:
        with self._idle:
            self._is_closing = True
            while self._active_requests > 0:
                self._idle.wait()

            if self._browser is not None:
                self._browser.close()
                self._browser = None
            if self._playwright is not None:
                self._playwright.stop()
                self._playwright = None
            self._is_closing = False

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    @contextmanager
    def _request_page(self, timeout_ms: int):
        with self._idle:
            browser = self._ensure_browser()
            self._active_requests += 1

        context = browser.new_context()
        page = context.new_page()
        page.set_default_timeout(timeout_ms)

        try:
            yield page
        finally:
            try:
                page.close()
            finally:
                context.close()
                with self._idle:
                    self._active_requests -= 1
                    if self._active_requests == 0:
                        self._idle.notify_all()

    def take_screenshot(
        self,
        url: str,
        full_page=False,
        wait_until: WaitUntil = "domcontentloaded",
        timeout_ms: int = 15000,
    ) -> bytes:
        with self._request_page(timeout_ms) as page:
            page.goto(url, wait_until=wait_until)
            return page.screenshot(full_page=full_page)

    def get_page_html(
        self,
        url: str,
        wait_until: WaitUntil = "domcontentloaded",
        timeout_ms: int = 15000,
    ) -> str:
        with self._request_page(timeout_ms) as page:
            page.goto(url, wait_until=wait_until)
            return page.content()

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

        html = self.get_page_html(url, wait_until=wait_until, timeout_ms=timeout_ms)
        r = html_to_markdown.convert(html)
        if not r.content:
            raise RuntimeError("Failed to convert HTML to markdown.")

        content = r.content[start_char:start_char + max_chars]

        if start_char > 0 or start_char + max_chars < len(r.content):
            content += "\n\n[Content truncated due to length limits...]"

        return content


def register_browser_tools(toolbox: ToolBox):
    browser = Browser()
    toolbox.register(browser.browser_get_page)