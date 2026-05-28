"""
TDD characterization tests for you.com service wait strategy.

RED phase: These tests assert wait_until="domcontentloaded" but current code
uses wait_until="networkidle". Tests for "fix" sites MUST FAIL before implementation.

Call sites covered:
  - services/you/service.py:70  (_navigate_to_signup) -> FIX -> domcontentloaded
  - services/you/service.py:184 (_verify_email)        -> FIX -> domcontentloaded
"""
import unittest
from unittest.mock import MagicMock, patch, call


class TestYouServiceWaitStrategy(unittest.TestCase):
    def setUp(self):
        self.mock_page = MagicMock()

    # -------------------------------------------------------------------------
    # Call site: you:70 - _navigate_to_signup -> page.goto("https://you.com/platform")
    # DECISION: fix -> wait_until="domcontentloaded"
    # STATUS: RED (current code uses networkidle)
    # -------------------------------------------------------------------------
    def test_navigate_to_signup_uses_domcontentloaded(self):
        """you:70 - dashboard navigation must use domcontentloaded, not networkidle."""
        from services.you.service import YouService
        service = YouService()

        with patch("time.sleep"):
            service._navigate_to_signup(self.mock_page)

        # page.goto must have been called
        self.assertTrue(
            self.mock_page.goto.called,
            "page.goto was not called in _navigate_to_signup",
        )

        # Find the call to https://you.com/platform
        platform_call = None
        for c in self.mock_page.goto.call_args_list:
            args, kwargs = c
            url = args[0] if args else kwargs.get("url", "")
            if "you.com/platform" in url and "api-keys" not in url:
                platform_call = c
                break

        self.assertIsNotNone(
            platform_call,
            "page.goto was not called with https://you.com/platform",
        )

        _, kwargs = platform_call
        self.assertEqual(
            kwargs.get("wait_until"),
            "domcontentloaded",
            f"you:70 must use wait_until='domcontentloaded', got {kwargs.get('wait_until')!r}",
        )

    def test_navigate_to_signup_preserves_timeout(self):
        """you:70 - timeout=30000 must be preserved after fix."""
        from services.you.service import YouService
        service = YouService()

        with patch("time.sleep"):
            service._navigate_to_signup(self.mock_page)

        platform_call = None
        for c in self.mock_page.goto.call_args_list:
            args, kwargs = c
            url = args[0] if args else kwargs.get("url", "")
            if "you.com/platform" in url and "api-keys" not in url:
                platform_call = c
                break

        self.assertIsNotNone(platform_call)
        _, kwargs = platform_call
        self.assertEqual(
            kwargs.get("timeout"),
            30000,
            f"you:70 timeout must be 30000, got {kwargs.get('timeout')!r}",
        )

    # -------------------------------------------------------------------------
    # Call site: you:184 - _verify_email -> page.goto("https://you.com/platform/api-keys")
    # DECISION: fix -> wait_until="domcontentloaded"
    # STATUS: RED (current code uses networkidle)
    # -------------------------------------------------------------------------
    def test_verify_email_api_keys_navigation_uses_domcontentloaded(self):
        """you:184 - API keys page navigation must use domcontentloaded, not networkidle."""
        from services.you.service import YouService
        service = YouService()

        with patch("time.sleep"), \
             patch("services.you.service.fill_first_input", side_effect=["otp-selector", None]), \
             patch("mail.factory.get_provider") as mock_provider_factory, \
             patch("config.EMAIL_CODE_TIMEOUT", 60):

            mock_provider = MagicMock()
            mock_provider.get_email_code.return_value = "123456"
            mock_provider_factory.return_value = mock_provider

            self.mock_page.wait_for_url.return_value = None
            self.mock_page.query_selector.return_value = None

            service._verify_email(self.mock_page, "test@example.com")

        # Find the call to https://you.com/platform/api-keys
        api_keys_call = None
        for c in self.mock_page.goto.call_args_list:
            args, kwargs = c
            url = args[0] if args else kwargs.get("url", "")
            if "api-keys" in url:
                api_keys_call = c
                break

        self.assertIsNotNone(
            api_keys_call,
            "page.goto was not called with https://you.com/platform/api-keys",
        )

        _, kwargs = api_keys_call
        self.assertEqual(
            kwargs.get("wait_until"),
            "domcontentloaded",
            f"you:184 must use wait_until='domcontentloaded', got {kwargs.get('wait_until')!r}",
        )

    def test_verify_email_api_keys_navigation_preserves_timeout(self):
        """you:184 - timeout=30000 must be preserved after fix."""
        from services.you.service import YouService
        service = YouService()

        with patch("time.sleep"), \
             patch("services.you.service.fill_first_input", side_effect=["otp-selector", None]), \
             patch("mail.factory.get_provider") as mock_provider_factory, \
             patch("config.EMAIL_CODE_TIMEOUT", 60):

            mock_provider = MagicMock()
            mock_provider.get_email_code.return_value = "123456"
            mock_provider_factory.return_value = mock_provider

            self.mock_page.wait_for_url.return_value = None
            self.mock_page.query_selector.return_value = None

            service._verify_email(self.mock_page, "test@example.com")

        api_keys_call = None
        for c in self.mock_page.goto.call_args_list:
            args, kwargs = c
            url = args[0] if args else kwargs.get("url", "")
            if "api-keys" in url:
                api_keys_call = c
                break

        self.assertIsNotNone(api_keys_call)
        _, kwargs = api_keys_call
        self.assertEqual(
            kwargs.get("timeout"),
            30000,
            f"you:184 timeout must be 30000, got {kwargs.get('timeout')!r}",
        )


if __name__ == "__main__":
    unittest.main()
