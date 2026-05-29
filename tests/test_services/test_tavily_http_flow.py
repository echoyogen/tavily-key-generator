"""
Tests for TavilyService HTTP-primary flow with Auth0 signup.
"""
import unittest
from unittest.mock import MagicMock, patch

from services.tavily.service import TavilyService


class TestTavilyHttpFlow(unittest.TestCase):
    def setUp(self):
        self.service = TavilyService()

    def test_register_http_success(self):
        mock_provider = MagicMock()
        mock_provider.get_verification_link.return_value = (
            "https://auth.tavily.com/u/email-verification?ticket=t1"
        )

        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 201
        mock_post_resp.json.return_value = {"_id": "uid1", "email": "t@x.com"}

        def get_side_effect(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            if "api-keys" in url or "app.tavily.com/app" in url:
                resp.text = "<html>tvly-testkey12345678901234</html>"
            else:
                resp.text = "<html>ok</html>"
            return resp

        with patch('services.tavily.service._solve_turnstile', return_value="fake-turnstile-token"), \
             patch('mail.factory.get_provider', return_value=mock_provider), \
             patch('services.tavily.service.std_requests.Session') as mock_session_cls, \
             patch.object(self.service, '_browser_fallback') as mock_fallback, \
             patch.object(self.service, '_pre_register_hook'), \
             patch.object(self.service, '_do_post_verify'), \
             patch.object(self.service, '_save_result'), \
             patch('time.sleep'):
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session
            mock_session.post.return_value = mock_post_resp
            mock_session.get.side_effect = get_side_effect

            result = self.service.register("t@x.com", "Pass123!")

        self.assertEqual(result, "tvly-testkey12345678901234")
        mock_fallback.assert_not_called()

    def test_register_http_fails_triggers_fallback(self):
        with patch('services.tavily.service._solve_turnstile', return_value=None), \
             patch.object(self.service, '_pre_register_hook'), \
             patch.object(self.service, '_browser_fallback', return_value="tvly-browserkey1234567890123456") as mock_fallback, \
             patch('time.sleep'):
            result = self.service.register("t@test.com", "pass")

        mock_fallback.assert_called_once_with("t@test.com", "pass")
        self.assertEqual(result, "tvly-browserkey1234567890123456")

    def test_pre_register_hook_raises_propagates_not_fallback(self):
        with patch.object(self.service, '_pre_register_hook', side_effect=RuntimeError("solver not ready")), \
             patch.object(self.service, '_browser_fallback', return_value="tvly-somekey1234567890") as mock_fallback, \
             patch('time.sleep'):
            with self.assertRaises(RuntimeError, msg="solver not ready"):
                self.service.register("t@test.com", "p")
        mock_fallback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
