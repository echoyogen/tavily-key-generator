"""
TDD characterization tests for tavily service wait strategy.

RED phase: Tests for "fix" sites assert wait_until="domcontentloaded" but current
code uses wait_until="networkidle". Tests for "keep" sites assert networkidle and
PASS immediately (documenting safe behavior).

Call sites covered:
  - services/tavily/service.py:293 (_refresh_password_page_if_needed) -> KEEP -> networkidle (PASS)
  - services/tavily/service.py:324 (_ensure_password_challenge_ready) -> KEEP -> networkidle (PASS)
  - services/tavily/service.py:457 (_navigate_to_signup)              -> FIX  -> domcontentloaded
  - services/tavily/service.py:465 (_navigate_to_signup)              -> FIX  -> domcontentloaded
  - services/tavily/service.py:567 (_verify_email)                    -> FIX  -> domcontentloaded
"""
import unittest
from unittest.mock import MagicMock, patch


class TestTavilyServiceWaitStrategy(unittest.TestCase):
    def setUp(self):
        self.mock_page = MagicMock()

    # -------------------------------------------------------------------------
    # Call site: tavily:293 - _refresh_password_page_if_needed
    # page.reload(wait_until="networkidle", timeout=30000)
    # DECISION: keep -> networkidle is correct for reload recovery
    # STATUS: GREEN (should PASS immediately - documents safe behavior)
    # -------------------------------------------------------------------------
    def test_refresh_password_page_reload_keeps_networkidle(self):
        """tavily:293 - password page reload recovery must keep networkidle (safe behavior)."""
        from services.tavily.service import _refresh_password_page_if_needed

        feedback = "couldn't load the security challenge"
        state = {}

        with patch("time.sleep"):
            _refresh_password_page_if_needed(self.mock_page, feedback, state)

        self.assertTrue(
            self.mock_page.reload.called,
            "page.reload was not called in _refresh_password_page_if_needed",
        )

        _, kwargs = self.mock_page.reload.call_args
        self.assertEqual(
            kwargs.get("wait_until"),
            "networkidle",
            f"tavily:293 must keep wait_until='networkidle', got {kwargs.get('wait_until')!r}",
        )

    def test_refresh_password_page_reload_followed_by_wait_for_selector(self):
        """tavily:293 - wait_for_selector must be called after reload (safety net)."""
        from services.tavily.service import _refresh_password_page_if_needed

        feedback = "couldn't load the security challenge"
        state = {}

        with patch("time.sleep"):
            _refresh_password_page_if_needed(self.mock_page, feedback, state)

        self.assertTrue(
            self.mock_page.wait_for_selector.called,
            "page.wait_for_selector was not called after reload in _refresh_password_page_if_needed",
        )

    # -------------------------------------------------------------------------
    # Call site: tavily:324 - _ensure_password_challenge_ready
    # page.reload(wait_until="networkidle", timeout=30000)
    # DECISION: keep -> networkidle is correct for reload recovery
    # STATUS: GREEN (should PASS immediately - documents safe behavior)
    # -------------------------------------------------------------------------
    def test_ensure_password_challenge_ready_reload_keeps_networkidle(self):
        """tavily:324 - challenge ready reload must keep networkidle (safe behavior)."""
        from services.tavily.service import _ensure_password_challenge_ready

        with patch("time.sleep"), \
             patch("services.tavily.service._wait_for_password_challenge_ready") as mock_wait:

            mock_wait.return_value = {
                "hasPasswordInput": True,
                "hasChallengeIframe": False,
                "hasTurnstile": False,
                "hasCaptchaDiv": True,
                "hasCaptchaInput": False,
            }

            _ensure_password_challenge_ready(self.mock_page)

        self.assertTrue(
            self.mock_page.reload.called,
            "page.reload was not called in _ensure_password_challenge_ready",
        )

        _, kwargs = self.mock_page.reload.call_args
        self.assertEqual(
            kwargs.get("wait_until"),
            "networkidle",
            f"tavily:324 must keep wait_until='networkidle', got {kwargs.get('wait_until')!r}",
        )

    def test_ensure_password_challenge_ready_reload_followed_by_wait_for_selector(self):
        """tavily:324 - wait_for_selector must be called after reload (safety net)."""
        from services.tavily.service import _ensure_password_challenge_ready

        with patch("time.sleep"), \
             patch("services.tavily.service._wait_for_password_challenge_ready") as mock_wait:

            mock_wait.return_value = {
                "hasPasswordInput": True,
                "hasChallengeIframe": False,
                "hasTurnstile": False,
                "hasCaptchaDiv": True,
                "hasCaptchaInput": False,
            }

            _ensure_password_challenge_ready(self.mock_page)

        self.assertTrue(
            self.mock_page.wait_for_selector.called,
            "page.wait_for_selector was not called after reload in _ensure_password_challenge_ready",
        )

    # -------------------------------------------------------------------------
    # Call site: tavily:457 - _navigate_to_signup
    # page.goto("https://app.tavily.com/sign-in", wait_until="networkidle", ...)
    # DECISION: fix -> wait_until="domcontentloaded"
    # STATUS: RED (current code uses networkidle)
    # -------------------------------------------------------------------------
    def test_navigate_to_signup_sign_in_uses_domcontentloaded(self):
        """tavily:457 - sign-in page navigation must use domcontentloaded, not networkidle."""
        from services.tavily.service import TavilyService
        service = TavilyService()

        with patch("time.sleep"):
            self.mock_page.content.return_value = "<html></html>"
            self.mock_page.query_selector.return_value = None

            service._navigate_to_signup(self.mock_page)

        sign_in_call = None
        for c in self.mock_page.goto.call_args_list:
            args, kwargs = c
            url = args[0] if args else kwargs.get("url", "")
            if "sign-in" in url:
                sign_in_call = c
                break

        self.assertIsNotNone(
            sign_in_call,
            "page.goto was not called with https://app.tavily.com/sign-in",
        )

        _, kwargs = sign_in_call
        self.assertEqual(
            kwargs.get("wait_until"),
            "domcontentloaded",
            f"tavily:457 must use wait_until='domcontentloaded', got {kwargs.get('wait_until')!r}",
        )

    # -------------------------------------------------------------------------
    # Call site: tavily:465 - _navigate_to_signup (signup_url extracted from HTML)
    # page.goto(signup_url, wait_until="networkidle", ...)
    # DECISION: fix -> wait_until="domcontentloaded"
    # STATUS: RED (current code uses networkidle)
    # -------------------------------------------------------------------------
    def test_navigate_to_signup_extracted_url_uses_domcontentloaded(self):
        """tavily:465 - extracted signup URL navigation must use domcontentloaded, not networkidle."""
        from services.tavily.service import TavilyService
        service = TavilyService()

        signup_path = '/u/signup/identifier?flow=signup'
        html_with_signup = f'<html><a href="{signup_path}">Sign up</a></html>'

        with patch("time.sleep"):
            self.mock_page.content.return_value = html_with_signup
            self.mock_page.query_selector.return_value = None

            service._navigate_to_signup(self.mock_page)

        signup_call = None
        for c in self.mock_page.goto.call_args_list:
            args, kwargs = c
            url = args[0] if args else kwargs.get("url", "")
            if "signup" in url and "sign-in" not in url:
                signup_call = c
                break

        self.assertIsNotNone(
            signup_call,
            "page.goto was not called with extracted signup URL",
        )

        _, kwargs = signup_call
        self.assertEqual(
            kwargs.get("wait_until"),
            "domcontentloaded",
            f"tavily:465 must use wait_until='domcontentloaded', got {kwargs.get('wait_until')!r}",
        )

    # -------------------------------------------------------------------------
    # Call site: tavily:567 - _verify_email
    # page.goto(verify_url, wait_until="networkidle", timeout=60000)
    # DECISION: fix -> wait_until="domcontentloaded"
    # STATUS: RED (current code uses networkidle)
    # -------------------------------------------------------------------------
    def test_verify_email_navigation_uses_domcontentloaded(self):
        """tavily:567 - verification link navigation must use domcontentloaded, not networkidle."""
        from services.tavily.service import TavilyService
        service = TavilyService()

        verify_url = "https://app.tavily.com/verify?token=abc123"

        with patch("time.sleep"), \
             patch("services.tavily.service._get_mail_provider") as mock_provider_factory:

            mock_provider = MagicMock()
            mock_provider.get_verification_link.return_value = verify_url
            mock_provider_factory.return_value = mock_provider

            self.mock_page.url = "https://app.tavily.com/verify"

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
            f"tavily:567 must use wait_until='domcontentloaded', got {kwargs.get('wait_until')!r}",
        )

    def test_verify_email_navigation_preserves_timeout(self):
        """tavily:567 - timeout=60000 must be preserved after fix."""
        from services.tavily.service import TavilyService
        service = TavilyService()

        verify_url = "https://app.tavily.com/verify?token=abc123"

        with patch("time.sleep"), \
             patch("services.tavily.service._get_mail_provider") as mock_provider_factory:

            mock_provider = MagicMock()
            mock_provider.get_verification_link.return_value = verify_url
            mock_provider_factory.return_value = mock_provider

            self.mock_page.url = "https://app.tavily.com/verify"

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
            f"tavily:567 timeout must be 60000, got {kwargs.get('timeout')!r}",
        )


if __name__ == "__main__":
    unittest.main()
