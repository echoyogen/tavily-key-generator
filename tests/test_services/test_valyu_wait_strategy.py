"""
TDD characterization tests for valyu service wait strategy.

RED phase: Tests assert wait_until="domcontentloaded" but current code uses
wait_until="networkidle". Tests for "fix" sites MUST FAIL before implementation.

Call sites covered:
  - services/valyu/service.py:88  (_navigate_to_signup) -> FIX -> domcontentloaded
  - services/valyu/service.py:177 (_verify_email)       -> FIX -> domcontentloaded
  - services/valyu/service.py:186 (_verify_email)       -> FIX -> domcontentloaded
"""
import unittest
from unittest.mock import MagicMock, patch


class TestValyuServiceWaitStrategy(unittest.TestCase):
    def setUp(self):
        self.mock_page = MagicMock()

    # -------------------------------------------------------------------------
    # Call site: valyu:88 - _navigate_to_signup
    # page.goto("https://platform.valyu.ai/auth/signup", wait_until="networkidle", ...)
    # DECISION: fix -> wait_until="domcontentloaded"
    # STATUS: RED (current code uses networkidle)
    # -------------------------------------------------------------------------
    def test_navigate_to_signup_uses_domcontentloaded(self):
        """valyu:88 - signup page navigation must use domcontentloaded, not networkidle."""
        from services.valyu.service import ValyuService
        service = ValyuService()

        with patch("time.sleep"), \
             patch("services.valyu.service.attach_response_tracker", return_value=[]):
            service._navigate_to_signup(self.mock_page)

        self.assertTrue(
            self.mock_page.goto.called,
            "page.goto was not called in _navigate_to_signup",
        )

        signup_call = None
        for c in self.mock_page.goto.call_args_list:
            args, kwargs = c
            url = args[0] if args else kwargs.get("url", "")
            if "auth/signup" in url:
                signup_call = c
                break

        self.assertIsNotNone(
            signup_call,
            "page.goto was not called with https://platform.valyu.ai/auth/signup",
        )

        _, kwargs = signup_call
        self.assertEqual(
            kwargs.get("wait_until"),
            "domcontentloaded",
            f"valyu:88 must use wait_until='domcontentloaded', got {kwargs.get('wait_until')!r}",
        )

    def test_navigate_to_signup_preserves_timeout(self):
        """valyu:88 - timeout=30000 must be preserved after fix."""
        from services.valyu.service import ValyuService
        service = ValyuService()

        with patch("time.sleep"), \
             patch("services.valyu.service.attach_response_tracker", return_value=[]):
            service._navigate_to_signup(self.mock_page)

        signup_call = None
        for c in self.mock_page.goto.call_args_list:
            args, kwargs = c
            url = args[0] if args else kwargs.get("url", "")
            if "auth/signup" in url:
                signup_call = c
                break

        self.assertIsNotNone(signup_call)
        _, kwargs = signup_call
        self.assertEqual(
            kwargs.get("timeout"),
            30000,
            f"valyu:88 timeout must be 30000, got {kwargs.get('timeout')!r}",
        )

    # -------------------------------------------------------------------------
    # Call site: valyu:177 - _verify_email (verification link navigation)
    # page.goto(verify_url, wait_until="networkidle", timeout=60000)
    # DECISION: fix -> wait_until="domcontentloaded"
    # STATUS: RED (current code uses networkidle)
    # -------------------------------------------------------------------------
    def test_verify_email_verification_link_uses_domcontentloaded(self):
        """valyu:177 - verification link navigation must use domcontentloaded, not networkidle."""
        from services.valyu.service import ValyuService
        service = ValyuService()

        verify_url = "https://platform.valyu.ai/verify?token=abc123"

        with patch("time.sleep"), \
             patch("mail.factory.get_provider") as mock_provider_factory, \
             patch("config.EMAIL_CODE_TIMEOUT", 60):

            mock_provider = MagicMock()
            mock_provider.get_verification_link.return_value = verify_url
            mock_provider_factory.return_value = mock_provider

            self.mock_page.url = "https://platform.valyu.ai/dashboard"
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
            f"valyu:177 must use wait_until='domcontentloaded', got {kwargs.get('wait_until')!r}",
        )

    def test_verify_email_verification_link_preserves_timeout(self):
        """valyu:177 - timeout=60000 must be preserved after fix."""
        from services.valyu.service import ValyuService
        service = ValyuService()

        verify_url = "https://platform.valyu.ai/verify?token=abc123"

        with patch("time.sleep"), \
             patch("mail.factory.get_provider") as mock_provider_factory, \
             patch("config.EMAIL_CODE_TIMEOUT", 60):

            mock_provider = MagicMock()
            mock_provider.get_verification_link.return_value = verify_url
            mock_provider_factory.return_value = mock_provider

            self.mock_page.url = "https://platform.valyu.ai/dashboard"
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
            f"valyu:177 timeout must be 60000, got {kwargs.get('timeout')!r}",
        )

    # -------------------------------------------------------------------------
    # Call site: valyu:186 - _verify_email (API keys page navigation)
    # page.goto("https://platform.valyu.ai/user/account/apikeys", wait_until="networkidle", ...)
    # DECISION: fix -> wait_until="domcontentloaded"
    # STATUS: RED (current code uses networkidle)
    # -------------------------------------------------------------------------
    def test_verify_email_api_keys_navigation_uses_domcontentloaded(self):
        """valyu:186 - API keys page navigation must use domcontentloaded, not networkidle."""
        from services.valyu.service import ValyuService
        service = ValyuService()

        verify_url = "https://platform.valyu.ai/verify?token=abc123"

        with patch("time.sleep"), \
             patch("mail.factory.get_provider") as mock_provider_factory, \
             patch("config.EMAIL_CODE_TIMEOUT", 60):

            mock_provider = MagicMock()
            mock_provider.get_verification_link.return_value = verify_url
            mock_provider_factory.return_value = mock_provider

            self.mock_page.url = "https://platform.valyu.ai/dashboard"
            self.mock_page.query_selector.return_value = None

            service._verify_email(self.mock_page, "test@example.com")

        api_keys_call = None
        for c in self.mock_page.goto.call_args_list:
            args, kwargs = c
            url = args[0] if args else kwargs.get("url", "")
            if "apikeys" in url:
                api_keys_call = c
                break

        self.assertIsNotNone(
            api_keys_call,
            "page.goto was not called with https://platform.valyu.ai/user/account/apikeys",
        )

        _, kwargs = api_keys_call
        self.assertEqual(
            kwargs.get("wait_until"),
            "domcontentloaded",
            f"valyu:186 must use wait_until='domcontentloaded', got {kwargs.get('wait_until')!r}",
        )

    def test_verify_email_api_keys_navigation_preserves_timeout(self):
        """valyu:186 - timeout=30000 must be preserved after fix."""
        from services.valyu.service import ValyuService
        service = ValyuService()

        verify_url = "https://platform.valyu.ai/verify?token=abc123"

        with patch("time.sleep"), \
             patch("mail.factory.get_provider") as mock_provider_factory, \
             patch("config.EMAIL_CODE_TIMEOUT", 60):

            mock_provider = MagicMock()
            mock_provider.get_verification_link.return_value = verify_url
            mock_provider_factory.return_value = mock_provider

            self.mock_page.url = "https://platform.valyu.ai/dashboard"
            self.mock_page.query_selector.return_value = None

            service._verify_email(self.mock_page, "test@example.com")

        api_keys_call = None
        for c in self.mock_page.goto.call_args_list:
            args, kwargs = c
            url = args[0] if args else kwargs.get("url", "")
            if "apikeys" in url:
                api_keys_call = c
                break

        self.assertIsNotNone(api_keys_call)
        _, kwargs = api_keys_call
        self.assertEqual(
            kwargs.get("timeout"),
            30000,
            f"valyu:186 timeout must be 30000, got {kwargs.get('timeout')!r}",
        )


if __name__ == "__main__":
    unittest.main()
