import unittest
from unittest.mock import MagicMock, patch

from xun.tools.browser import Browser


class BrowserLifecycleTest(unittest.TestCase):
    def test_starts_and_closes_a_browser_for_each_operation(self) -> None:
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

        self.assertEqual(factory.start.call_count, 2)
        self.assertEqual(playwright.chromium.launch.call_count, 2)
        self.assertEqual(chromium.new_context.call_count, 2)
        self.assertEqual(context.close.call_count, 2)
        self.assertEqual(chromium.close.call_count, 2)
        self.assertEqual(playwright.stop.call_count, 2)


if __name__ == "__main__":
    unittest.main()