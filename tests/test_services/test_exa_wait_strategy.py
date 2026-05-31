"""
TDD characterization tests for exa.ai service wait strategy.

RED phase: Tests assert wait_until="domcontentloaded" but current code uses
wait_until="networkidle". Tests for "fix" sites MUST FAIL before implementation.

Call sites covered:
  - services/exa/service.py:68 (_ensure_dashboard_ready) -> FIX -> domcontentloaded
  - services/exa/service.py:80 (_navigate_to_signup)     -> FIX -> domcontentloaded
"""
import unittest
from unittest.mock import MagicMock, patch


class TestExaServiceWaitStrategy(unittest.TestCase):
    def setUp(self):
        self.mock_page = MagicMock()

    # -------------------------------------------------------------------------
    # Call site: exa:68 - _ensure_dashboard_ready (module-level function)
    # page.goto(_EXA_HOME_URL, wait_until="networkidle", ...)
    # DECISION: fix -> wait_until="domcontentloaded"
    # STATUS: RED (current code uses networkidle)
    # -------------------------------------------------------------------------
    def test_ensure_dashboard_ready_uses_domcontentloaded(self):
        """exa:68 - dashboard home navigation must use domcontentloaded, not networkidle."""
        from services.exa.service import _ensure_dashboard_ready, _EXA_HOME_URL

        # Simulate page is on dashboard but not on /home -> triggers goto
        self.mock_page.url = "https://dashboard.exa.ai/api-keys"

        with patch("time.sleep"):
            _ensure_dashboard_ready(self.mock_page)

        self.assertTrue(
            self.mock_page.goto.called,
            "page.goto was not called in _ensure_dashboard_ready",
        )

        home_call = None
        for c in self.mock_page.goto.call_args_list:
            args, kwargs = c
            url = args[0] if args else kwargs.get("url", "")
            if _EXA_HOME_URL in url:
                home_call = c
                break

        self.assertIsNotNone(
            home_call,
            f"page.goto was not called with {_EXA_HOME_URL}",
        )

        _, kwargs = home_call
        self.assertEqual(
            kwargs.get("wait_until"),
            "domcontentloaded",
            f"exa:68 must use wait_until='domcontentloaded', got {kwargs.get('wait_until')!r}",
        )

    def test_ensure_dashboard_ready_preserves_timeout(self):
        """exa:68 - timeout=30000 must be preserved after fix."""
        from services.exa.service import _ensure_dashboard_ready, _EXA_HOME_URL

        self.mock_page.url = "https://dashboard.exa.ai/api-keys"

        with patch("time.sleep"):
            _ensure_dashboard_ready(self.mock_page)

        home_call = None
        for c in self.mock_page.goto.call_args_list:
            args, kwargs = c
            url = args[0] if args else kwargs.get("url", "")
            if _EXA_HOME_URL in url:
                home_call = c
                break

        self.assertIsNotNone(home_call)
        _, kwargs = home_call
        self.assertEqual(
            kwargs.get("timeout"),
            30000,
            f"exa:68 timeout must be 30000, got {kwargs.get('timeout')!r}",
        )

    # -------------------------------------------------------------------------
    # Call site: exa:80 - _navigate_to_signup -> page.goto(_EXA_AUTH_URL)
    # DECISION: fix -> wait_until="domcontentloaded"
    # STATUS: RED (current code uses networkidle)
    # -------------------------------------------------------------------------
    def test_navigate_to_signup_uses_domcontentloaded(self):
        """exa:80 - auth page navigation must use domcontentloaded, not networkidle."""
        from services.exa.service import ExaService, _EXA_AUTH_URL
        service = ExaService()

        with patch("time.sleep"):
            service._navigate_to_signup(self.mock_page)

        self.assertTrue(
            self.mock_page.goto.called,
            "page.goto was not called in _navigate_to_signup",
        )

        auth_call = None
        for c in self.mock_page.goto.call_args_list:
            args, kwargs = c
            url = args[0] if args else kwargs.get("url", "")
            if _EXA_AUTH_URL in url:
                auth_call = c
                break

        self.assertIsNotNone(
            auth_call,
            f"page.goto was not called with {_EXA_AUTH_URL}",
        )

        _, kwargs = auth_call
        self.assertEqual(
            kwargs.get("wait_until"),
            "domcontentloaded",
            f"exa:80 must use wait_until='domcontentloaded', got {kwargs.get('wait_until')!r}",
        )

    def test_navigate_to_signup_preserves_timeout(self):
        """exa:80 - timeout=30000 must be preserved after fix."""
        from services.exa.service import ExaService, _EXA_AUTH_URL
        service = ExaService()

        with patch("time.sleep"):
            service._navigate_to_signup(self.mock_page)

        auth_call = None
        for c in self.mock_page.goto.call_args_list:
            args, kwargs = c
            url = args[0] if args else kwargs.get("url", "")
            if _EXA_AUTH_URL in url:
                auth_call = c
                break

        self.assertIsNotNone(auth_call)
        _, kwargs = auth_call
        self.assertEqual(
            kwargs.get("timeout"),
            30000,
            f"exa:80 timeout must be 30000, got {kwargs.get('timeout')!r}",
        )


if __name__ == "__main__":
    unittest.main()
