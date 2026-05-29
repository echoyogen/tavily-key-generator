import unittest
from unittest.mock import MagicMock, patch

from services.serper.service import SerperService


class TestSerperHttpFlow(unittest.TestCase):
    def setUp(self):
        self.service = SerperService()
        self.mock_provider = MagicMock()
        self.mock_provider.get_verification_link.return_value = "https://serper.dev/verify?token=t1"

    def test_register_http_success(self):
        signup_page_mock = MagicMock()
        signup_page_mock.text = "<html><body>signup form</body></html>"

        post_resp_mock = MagicMock()
        post_resp_mock.text = "check your email to continue"
        post_resp_mock.url = "https://serper.dev/signup"
        post_resp_mock.status_code = 200

        verify_mock = MagicMock()
        verify_mock.status_code = 200

        dashboard_mock = MagicMock()
        dashboard_mock.text = "Your API key: ABCDEFGHIJKLMNOPQRSTUVWXYZ123456 use it"

        mock_session = MagicMock()

        def mock_get(url, **kwargs):
            if "verify" in url:
                return verify_mock
            if "dashboard" in url or "api-keys" in url:
                return dashboard_mock
            return signup_page_mock

        mock_session.get.side_effect = mock_get
        mock_session.post.return_value = post_resp_mock

        with patch("services.serper.service.requests.Session", return_value=mock_session), \
             patch("mail.factory.get_provider", return_value=self.mock_provider), \
             patch.object(self.service, "_browser_fallback") as mock_fallback, \
             patch.object(self.service, "_do_post_verify"), \
             patch.object(self.service, "_save_result"):
            result = self.service.register("test@example.com", "pass")

        self.assertEqual(result, "ABCDEFGHIJKLMNOPQRSTUVWXYZ123456")
        mock_fallback.assert_not_called()

    def test_register_http_fails_triggers_fallback(self):
        import requests as req

        mock_session = MagicMock()
        mock_session.get.side_effect = req.exceptions.ConnectionError("connection refused")

        with patch("services.serper.service.requests.Session", return_value=mock_session), \
             patch("mail.factory.get_provider", return_value=self.mock_provider), \
             patch.object(self.service, "_browser_fallback", return_value="serper-fallback-key-1234567890123") as mock_fallback:
            result = self.service.register("test@example.com", "pass")

        mock_fallback.assert_called_once_with("test@example.com", "pass")
        self.assertEqual(result, "serper-fallback-key-1234567890123")

    def test_register_both_fail_returns_none(self):
        import requests as req

        mock_session = MagicMock()
        mock_session.get.side_effect = req.exceptions.ConnectionError("connection refused")

        with patch("services.serper.service.requests.Session", return_value=mock_session), \
             patch("mail.factory.get_provider", return_value=self.mock_provider), \
             patch.object(self.service, "_browser_fallback", return_value=None):
            result = self.service.register("test@example.com", "pass")

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
