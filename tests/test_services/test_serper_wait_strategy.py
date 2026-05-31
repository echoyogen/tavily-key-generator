"""
TDD characterization tests for serper service wait strategy.

RED phase: Tests assert wait_until="domcontentloaded" but current code uses
wait_until="networkidle". Tests for "fix" sites MUST FAIL before implementation.

Call sites covered:
  - services/serper/service.py:74  (_navigate_to_signup) -> FIX -> domcontentloaded
  - services/serper/service.py:166 (_verify_email)       -> FIX -> domcontentloaded
  - services/serper/service.py:199 (_verify_email loop)  -> FIX -> domcontentloaded
"""
import unittest
from unittest.mock import MagicMock, patch


class TestSerperServiceWaitStrategy(unittest.TestCase):
    def setUp(self):
        self.mock_page = MagicMock()

    # -------------------------------------------------------------------------
    # Call site: serper:74 - _navigate_to_signup
    # page.goto("https://serper.dev/signup", wait_until="networkidle", ...)
    # DECISION: fix -> wait_until="domcontentloaded"
    # STATUS: RED (current code uses networkidle)
    # -------------------------------------------------------------------------
    def test_navigate_to_signup_uses_domcontentloaded(self):
        """serper:74 - signup page navigation must use domcontentloaded, not networkidle."""
        from services.serper.service import SerperService
        service = SerperService()

        with patch("time.sleep"):
            service._navigate_to_signup(self.mock_page)

        self.assertTrue(
            self.mock_page.goto.called,
            "page.goto was not called in _navigate_to_signup",
        )

        signup_call = None
        for c in self.mock_page.goto.call_args_list:
            args, kwargs = c
            url = args[0] if args else kwargs.get("url", "")
            if "serper.dev/signup" in url:
                signup_call = c
                break

        self.assertIsNotNone(
            signup_call,
            "page.goto was not called with https://serper.dev/signup",
        )

        _, kwargs = signup_call
        self.assertEqual(
            kwargs.get("wait_until"),
            "domcontentloaded",
            f"serper:74 must use wait_until='domcontentloaded', got {kwargs.get('wait_until')!r}",
        )

    def test_navigate_to_signup_preserves_timeout(self):
        """serper:74 - timeout=30000 must be preserved after fix."""
        from services.serper.service import SerperService
        service = SerperService()

        with patch("time.sleep"):
            service._navigate_to_signup(self.mock_page)

        signup_call = None
        for c in self.mock_page.goto.call_args_list:
            args, kwargs = c
            url = args[0] if args else kwargs.get("url", "")
            if "serper.dev/signup" in url:
                signup_call = c
                break

        self.assertIsNotNone(signup_call)
        _, kwargs = signup_call
        self.assertEqual(
            kwargs.get("timeout"),
            30000,
            f"serper:74 timeout must be 30000, got {kwargs.get('timeout')!r}",
        )

    # -------------------------------------------------------------------------
    # Call site: serper:166 - _verify_email
    # page.goto(verify_url, wait_until="networkidle", timeout=60000)
    # DECISION: fix -> wait_until="domcontentloaded"
    # STATUS: RED (current code uses networkidle)
    # -------------------------------------------------------------------------
    def test_verify_email_navigation_uses_domcontentloaded(self):
        """serper:166 - verification link navigation must use domcontentloaded, not networkidle."""
        from services.serper.service import SerperService
        service = SerperService()

        verify_url = "https://serper.dev/verify?token=abc123"

        with patch("time.sleep"), \
             patch("mail.factory.get_provider") as mock_provider_factory, \
             patch("config.EMAIL_CODE_TIMEOUT", 60):

            mock_provider = MagicMock()
            mock_provider.get_verification_link.return_value = verify_url
            mock_provider_factory.return_value = mock_provider

            self.mock_page.url = "https://serper.dev/dashboard"
            self.mock_page.query_selector.return_value = None

            service._verify_email(self.mock_page, "test@example.com")

        verify_call = None
        for c in self.mock_page.goto.call_args_list:
            args, kwargs = c
            url = args[0] if args else kwargs.get("url", "")
            if verify_url in url:
                verify_call = c
                break

        self.assertIsNotNone(
            verify_call,
            f"page.goto was not called with verify_url={verify_url}",
        )

        _, kwargs = verify_call
        self.assertEqual(
            kwargs.get("wait_until"),
            "domcontentloaded",
            f"serper:166 must use wait_until='domcontentloaded', got {kwargs.get('wait_until')!r}",
        )

    def test_verify_email_navigation_preserves_timeout(self):
        """serper:166 - timeout=60000 must be preserved after fix."""
        from services.serper.service import SerperService
        service = SerperService()

        verify_url = "https://serper.dev/verify?token=abc123"

        with patch("time.sleep"), \
             patch("mail.factory.get_provider") as mock_provider_factory, \
             patch("config.EMAIL_CODE_TIMEOUT", 60):

            mock_provider = MagicMock()
            mock_provider.get_verification_link.return_value = verify_url
            mock_provider_factory.return_value = mock_provider

            self.mock_page.url = "https://serper.dev/dashboard"
            self.mock_page.query_selector.return_value = None

            service._verify_email(self.mock_page, "test@example.com")

        verify_call = None
        for c in self.mock_page.goto.call_args_list:
            args, kwargs = c
            url = args[0] if args else kwargs.get("url", "")
            if verify_url in url:
                verify_call = c
                break

        self.assertIsNotNone(verify_call)
        _, kwargs = verify_call
        self.assertEqual(
            kwargs.get("timeout"),
            60000,
            f"serper:166 timeout must be 60000, got {kwargs.get('timeout')!r}",
        )

    # -------------------------------------------------------------------------
    # Call site: serper:199 - _verify_email (API keys page loop)
    # page.goto(url, wait_until="networkidle", timeout=15000)
    # DECISION: fix -> wait_until="domcontentloaded"
    # STATUS: RED (current code uses networkidle)
    # -------------------------------------------------------------------------
    def test_verify_email_api_keys_loop_uses_domcontentloaded(self):
        """serper:199 - API keys page loop navigation must use domcontentloaded, not networkidle."""
        from services.serper.service import SerperService
        service = SerperService()

        verify_url = "https://serper.dev/verify?token=abc123"

        with patch("time.sleep"), \
             patch("mail.factory.get_provider") as mock_provider_factory, \
             patch("config.EMAIL_CODE_TIMEOUT", 60):

            mock_provider = MagicMock()
            mock_provider.get_verification_link.return_value = verify_url
            mock_provider_factory.return_value = mock_provider

            self.mock_page.url = "https://serper.dev/dashboard"
            self.mock_page.query_selector.return_value = None

            service._verify_email(self.mock_page, "test@example.com")

        api_key_calls = [
            c for c in self.mock_page.goto.call_args_list
            if any(
                domain in (c[0][0] if c[0] else c[1].get("url", ""))
                for domain in ("serper.dev/dashboard", "serper.dev/api-keys")
            )
        ]

        self.assertTrue(
            len(api_key_calls) > 0,
            "page.goto was not called with dashboard or api-keys URL in _verify_email",
        )

        for c in api_key_calls:
            _, kwargs = c
            self.assertEqual(
                kwargs.get("wait_until"),
                "domcontentloaded",
                f"serper:199 must use wait_until='domcontentloaded', got {kwargs.get('wait_until')!r}",
            )

    def test_verify_email_api_keys_loop_preserves_timeout(self):
        """serper:199 - timeout=15000 must be preserved after fix."""
        from services.serper.service import SerperService
        service = SerperService()

        verify_url = "https://serper.dev/verify?token=abc123"

        with patch("time.sleep"), \
             patch("mail.factory.get_provider") as mock_provider_factory, \
             patch("config.EMAIL_CODE_TIMEOUT", 60):

            mock_provider = MagicMock()
            mock_provider.get_verification_link.return_value = verify_url
            mock_provider_factory.return_value = mock_provider

            self.mock_page.url = "https://serper.dev/dashboard"
            self.mock_page.query_selector.return_value = None

            service._verify_email(self.mock_page, "test@example.com")

        api_key_calls = [
            c for c in self.mock_page.goto.call_args_list
            if any(
                domain in (c[0][0] if c[0] else c[1].get("url", ""))
                for domain in ("serper.dev/dashboard", "serper.dev/api-keys")
            )
        ]

        self.assertTrue(len(api_key_calls) > 0)

        for c in api_key_calls:
            _, kwargs = c
            self.assertEqual(
                kwargs.get("timeout"),
                15000,
                f"serper:199 timeout must be 15000, got {kwargs.get('timeout')!r}",
            )


if __name__ == "__main__":
    unittest.main()
