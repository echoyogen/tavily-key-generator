"""
Regression tests for YouService browser launch behavior.

Verifies:
1. YouService._open_browser() uses Patchright/Chromium (not Camoufox)
2. Proxy is wired through when present
3. Headless config is respected
4. Context manager yields browser context with new_page() support
"""
import contextlib
import unittest
from unittest.mock import MagicMock, patch, call


class TestYouBrowserLaunch(unittest.TestCase):
    def _make_mock_playwright(self):
        """Create a mock playwright context manager with chromium browser."""
        mock_ctx = MagicMock()
        mock_browser = MagicMock()
        mock_browser.new_context.return_value = mock_ctx
        mock_p = MagicMock()
        mock_p.chromium.launch.return_value = mock_browser
        mock_sp_cm = MagicMock()
        mock_sp_cm.__enter__ = MagicMock(return_value=mock_p)
        mock_sp_cm.__exit__ = MagicMock(return_value=False)
        mock_sync_playwright = MagicMock(return_value=mock_sp_cm)
        return mock_sync_playwright, mock_p, mock_browser, mock_ctx

    def test_you_open_browser_uses_patchright_chromium(self):
        """YouService._open_browser() must use patchright chromium (sync_playwright entry point)."""
        from services.you.service import YouService

        mock_sync_playwright, mock_p, mock_browser, mock_ctx = self._make_mock_playwright()

        with patch("services.you.service.sync_playwright", mock_sync_playwright), \
             patch("services.you.service.get_proxy_dict", return_value=None):
            service = YouService()
            with service._open_browser() as ctx:
                pass

        # Verify sync_playwright was called (patchright entry point)
        mock_sync_playwright.assert_called_once()

        # Verify chromium.launch was called
        mock_p.chromium.launch.assert_called_once()

        # Verify browser.new_context was called
        mock_browser.new_context.assert_called_once()

        # Verify cleanup was called
        mock_ctx.close.assert_called_once()
        mock_browser.close.assert_called_once()

    def test_you_open_browser_no_proxy_when_none(self):
        """When get_proxy_dict() returns None, new_context() called without proxy."""
        from services.you.service import YouService

        mock_sync_playwright, mock_p, mock_browser, mock_ctx = self._make_mock_playwright()

        with patch("services.you.service.sync_playwright", mock_sync_playwright), \
             patch("services.you.service.get_proxy_dict", return_value=None):
            service = YouService()
            with service._open_browser() as ctx:
                pass

        # new_context() should be called without proxy argument
        mock_browser.new_context.assert_called_once_with()

    def test_you_open_browser_with_proxy(self):
        """When get_proxy_dict() returns proxy dict, new_context(proxy=...) is called."""
        from services.you.service import YouService

        mock_sync_playwright, mock_p, mock_browser, mock_ctx = self._make_mock_playwright()
        proxy_dict = {"server": "http://proxy:8080"}

        with patch("services.you.service.sync_playwright", mock_sync_playwright), \
             patch("services.you.service.get_proxy_dict", return_value=proxy_dict):
            service = YouService()
            with service._open_browser() as ctx:
                pass

        # new_context() should be called with proxy argument
        mock_browser.new_context.assert_called_once_with(proxy=proxy_dict)

    def test_you_open_browser_respects_headless_config(self):
        """When YOU_REGISTER_HEADLESS=False, chromium.launch(headless=False) is called."""
        from services.you.service import YouService

        mock_sync_playwright, mock_p, mock_browser, mock_ctx = self._make_mock_playwright()

        with patch("services.you.service.sync_playwright", mock_sync_playwright), \
             patch("services.you.service.get_proxy_dict", return_value=None), \
             patch("config.YOU_REGISTER_HEADLESS", False):
            service = YouService()
            with service._open_browser() as ctx:
                pass

        # chromium.launch should be called with headless=False
        mock_p.chromium.launch.assert_called_once_with(headless=False)

    def test_you_open_browser_respects_headless_config_true(self):
        """When YOU_REGISTER_HEADLESS=True (default), chromium.launch(headless=True) is called."""
        from services.you.service import YouService

        mock_sync_playwright, mock_p, mock_browser, mock_ctx = self._make_mock_playwright()

        with patch("services.you.service.sync_playwright", mock_sync_playwright), \
             patch("services.you.service.get_proxy_dict", return_value=None), \
             patch("config.YOU_REGISTER_HEADLESS", True):
            service = YouService()
            with service._open_browser() as ctx:
                pass

        # chromium.launch should be called with headless=True
        mock_p.chromium.launch.assert_called_once_with(headless=True)

    def test_you_open_browser_yields_context_with_new_page(self):
        """The yielded object from _open_browser() is the browser context."""
        from services.you.service import YouService

        mock_sync_playwright, mock_p, mock_browser, mock_ctx = self._make_mock_playwright()

        with patch("services.you.service.sync_playwright", mock_sync_playwright), \
             patch("services.you.service.get_proxy_dict", return_value=None):
            service = YouService()
            with service._open_browser() as ctx:
                # The yielded object should be the mock context
                self.assertIs(ctx, mock_ctx)
                # Context should support new_page()
                self.assertTrue(hasattr(ctx, "new_page"))

    def test_you_open_browser_cleanup_on_exception(self):
        """Browser and context are closed even if exception occurs in with block."""
        from services.you.service import YouService

        mock_sync_playwright, mock_p, mock_browser, mock_ctx = self._make_mock_playwright()

        with patch("services.you.service.sync_playwright", mock_sync_playwright), \
             patch("services.you.service.get_proxy_dict", return_value=None):
            service = YouService()
            try:
                with service._open_browser() as ctx:
                    raise ValueError("Test exception")
            except ValueError:
                pass

        # Cleanup should still be called
        mock_ctx.close.assert_called_once()
        mock_browser.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
