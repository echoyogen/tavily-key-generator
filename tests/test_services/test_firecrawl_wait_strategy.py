"""
TDD characterization tests for firecrawl service wait strategy.

RED phase: Tests assert wait_until="domcontentloaded" but current code uses
wait_until="networkidle". Tests for "fix" sites MUST FAIL before implementation.

Call sites covered:
  - services/firecrawl/service.py:22  (_navigate_to_signup) -> FIX -> domcontentloaded
  - services/firecrawl/service.py:91  (_verify_email)       -> FIX -> domcontentloaded
  - services/firecrawl/service.py:148 (_extract_api_key)    -> FIX -> domcontentloaded
"""
import unittest
from unittest.mock import MagicMock, patch


class TestFirecrawlServiceWaitStrategy(unittest.TestCase):
    def setUp(self):
        self.mock_page = MagicMock()

    # -------------------------------------------------------------------------
    # Call site: firecrawl:22 - _navigate_to_signup
    # page.goto("https://firecrawl.dev/", wait_until="networkidle", ...)
    # DECISION: fix -> wait_until="domcontentloaded"
    # STATUS: RED (current code uses networkidle)
    # -------------------------------------------------------------------------
    def test_navigate_to_signup_uses_domcontentloaded(self):
        """firecrawl:22 - landing page navigation must use domcontentloaded, not networkidle."""
        from services.firecrawl.service import FirecrawlService
        service = FirecrawlService()

        with patch("time.sleep"):
            service._navigate_to_signup(self.mock_page)

        self.assertTrue(
            self.mock_page.goto.called,
            "page.goto was not called in _navigate_to_signup",
        )

        landing_call = None
        for c in self.mock_page.goto.call_args_list:
            args, kwargs = c
            url = args[0] if args else kwargs.get("url", "")
            if "firecrawl.dev" in url and "api" not in url:
                landing_call = c
                break

        self.assertIsNotNone(
            landing_call,
            "page.goto was not called with https://firecrawl.dev/",
        )

        _, kwargs = landing_call
        self.assertEqual(
            kwargs.get("wait_until"),
            "domcontentloaded",
            f"firecrawl:22 must use wait_until='domcontentloaded', got {kwargs.get('wait_until')!r}",
        )

    def test_navigate_to_signup_preserves_timeout(self):
        """firecrawl:22 - timeout=30000 must be preserved after fix."""
        from services.firecrawl.service import FirecrawlService
        service = FirecrawlService()

        with patch("time.sleep"):
            service._navigate_to_signup(self.mock_page)

        landing_call = None
        for c in self.mock_page.goto.call_args_list:
            args, kwargs = c
            url = args[0] if args else kwargs.get("url", "")
            if "firecrawl.dev" in url and "api" not in url:
                landing_call = c
                break

        self.assertIsNotNone(landing_call)
        _, kwargs = landing_call
        self.assertEqual(
            kwargs.get("timeout"),
            30000,
            f"firecrawl:22 timeout must be 30000, got {kwargs.get('timeout')!r}",
        )

    # -------------------------------------------------------------------------
    # Call site: firecrawl:91 - _verify_email
    # page.goto(verify_url, wait_until="networkidle", timeout=60000)
    # DECISION: fix -> wait_until="domcontentloaded"
    # STATUS: RED (current code uses networkidle)
    # -------------------------------------------------------------------------
    def test_verify_email_navigation_uses_domcontentloaded(self):
        """firecrawl:91 - verification link navigation must use domcontentloaded, not networkidle."""
        from services.firecrawl.service import FirecrawlService
        service = FirecrawlService()

        verify_url = "https://firecrawl.dev/verify?token=abc123"

        with patch("time.sleep"), \
             patch("mail.factory.get_provider") as mock_provider_factory, \
             patch("config.EMAIL_CODE_TIMEOUT", 60):

            mock_provider = MagicMock()
            mock_provider.get_verification_link.return_value = verify_url
            mock_provider_factory.return_value = mock_provider

            self.mock_page.url = "https://firecrawl.dev/dashboard"
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
            f"firecrawl:91 must use wait_until='domcontentloaded', got {kwargs.get('wait_until')!r}",
        )

    def test_verify_email_navigation_preserves_timeout(self):
        """firecrawl:91 - timeout=60000 must be preserved after fix."""
        from services.firecrawl.service import FirecrawlService
        service = FirecrawlService()

        verify_url = "https://firecrawl.dev/verify?token=abc123"

        with patch("time.sleep"), \
             patch("mail.factory.get_provider") as mock_provider_factory, \
             patch("config.EMAIL_CODE_TIMEOUT", 60):

            mock_provider = MagicMock()
            mock_provider.get_verification_link.return_value = verify_url
            mock_provider_factory.return_value = mock_provider

            self.mock_page.url = "https://firecrawl.dev/dashboard"
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
            f"firecrawl:91 timeout must be 60000, got {kwargs.get('timeout')!r}",
        )

    # -------------------------------------------------------------------------
    # Call site: firecrawl:148 - _extract_api_key (loop)
    # page.goto(url, wait_until="networkidle", timeout=15000)
    # DECISION: fix -> wait_until="domcontentloaded"
    # STATUS: RED (current code uses networkidle)
    # -------------------------------------------------------------------------
    def test_extract_api_key_loop_navigation_uses_domcontentloaded(self):
        """firecrawl:148 - API key page loop navigation must use domcontentloaded, not networkidle."""
        from services.firecrawl.service import FirecrawlService
        service = FirecrawlService()

        with patch("time.sleep"), \
             patch("services.firecrawl.service.extract_api_key_by_pattern", return_value=None):

            self.mock_page.query_selector.return_value = None
            self.mock_page.url = "https://www.firecrawl.dev/app/api-keys"

            service._extract_api_key(self.mock_page)

        api_key_calls = [
            c for c in self.mock_page.goto.call_args_list
            if "firecrawl" in (c[0][0] if c[0] else c[1].get("url", ""))
        ]

        self.assertTrue(
            len(api_key_calls) > 0,
            "page.goto was not called in _extract_api_key loop",
        )

        for c in api_key_calls:
            _, kwargs = c
            self.assertEqual(
                kwargs.get("wait_until"),
                "domcontentloaded",
                f"firecrawl:148 must use wait_until='domcontentloaded', got {kwargs.get('wait_until')!r}",
            )

    def test_extract_api_key_loop_navigation_preserves_timeout(self):
        """firecrawl:148 - timeout=15000 must be preserved after fix."""
        from services.firecrawl.service import FirecrawlService
        service = FirecrawlService()

        with patch("time.sleep"), \
             patch("services.firecrawl.service.extract_api_key_by_pattern", return_value=None):

            self.mock_page.query_selector.return_value = None
            self.mock_page.url = "https://www.firecrawl.dev/app/api-keys"

            service._extract_api_key(self.mock_page)

        api_key_calls = [
            c for c in self.mock_page.goto.call_args_list
            if "firecrawl" in (c[0][0] if c[0] else c[1].get("url", ""))
        ]

        self.assertTrue(len(api_key_calls) > 0)

        for c in api_key_calls:
            _, kwargs = c
            self.assertEqual(
                kwargs.get("timeout"),
                15000,
                f"firecrawl:148 timeout must be 15000, got {kwargs.get('timeout')!r}",
            )


if __name__ == "__main__":
    unittest.main()
