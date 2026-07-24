import unittest
from unittest.mock import MagicMock, patch

from xun.tools.browser import Browser


class BrowserLifecycleTest(unittest.TestCase):
    def test_starts_playwright_and_browser_once(self) -> None:
        playwright = MagicMock()
        chromium = MagicMock()
        context = MagicMock()
        page = MagicMock()
        factory = MagicMock()
        factory.start.return_value = playwright
        playwright.chromium.launch.return_value = chromium
        chromium.new_context.return_value = context
        context.new_page.return_value = page

        with patch("xun.tools.browser.sync_playwright", return_value=factory):
            browser = Browser()
            self.assertTrue(browser._with_page(100, lambda current_page: current_page is page))
            self.assertTrue(browser._with_page(200, lambda current_page: current_page is page))
            browser.close()

        factory.start.assert_called_once_with()
        playwright.chromium.launch.assert_called_once_with()
        self.assertEqual(chromium.new_context.call_count, 2)
        self.assertEqual(context.close.call_count, 2)
        chromium.close.assert_called_once_with()
        playwright.stop.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()