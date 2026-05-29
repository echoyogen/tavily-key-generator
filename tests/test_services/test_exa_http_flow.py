import unittest
from unittest.mock import MagicMock, patch

from services.exa.service import ExaService


class TestExaServiceHttpPrimary(unittest.TestCase):
    def setUp(self):
        self.service = ExaService()
        self.mock_provider = MagicMock()
        self.mock_provider.get_existing_message_ids.return_value = set()
        self.mock_provider.get_verification_link.return_value = (
            "https://dashboard.exa.ai/api/auth/callback/email?token=t1"
        )

    def test_register_http_success(self):
        mock_session = MagicMock()
        csrf_response = MagicMock()
        csrf_response.json.return_value = {"csrfToken": "abc"}
        keys_response = MagicMock()
        keys_response.json.return_value = {"apiKeys": [{"id": "00000000-0000-0000-0000-000000000001"}]}
        keys_response.status_code = 200

        def mock_get(url, **kwargs):
            if "csrf" in url:
                return csrf_response
            return keys_response

        mock_session.get.side_effect = mock_get
        mock_session.post.return_value = MagicMock(status_code=200)

        with patch("requests.Session", return_value=mock_session), \
             patch("mail.factory.get_provider", return_value=self.mock_provider), \
             patch.object(self.service, "_browser_fallback") as mock_fallback, \
             patch.object(self.service, "_do_post_verify"), \
             patch.object(self.service, "_save_result"):
            result = self.service.register("test@example.com", "passw0rd")

        self.assertEqual(result, "00000000-0000-0000-0000-000000000001")
        mock_fallback.assert_not_called()

    def test_register_http_fails_triggers_fallback(self):
        import requests as req_lib

        mock_session = MagicMock()
        mock_session.get.side_effect = req_lib.exceptions.Timeout("timed out")

        with patch("requests.Session", return_value=mock_session), \
             patch("mail.factory.get_provider", return_value=self.mock_provider), \
             patch.object(self.service, "_browser_fallback", return_value="exa-browser-uuid") as mock_fallback:
            result = self.service.register("test@example.com", "passw0rd")

        mock_fallback.assert_called_once_with("test@example.com", "passw0rd")
        self.assertEqual(result, "exa-browser-uuid")

    def test_register_both_fail_returns_none(self):
        import requests as req_lib

        mock_session = MagicMock()
        mock_session.get.side_effect = req_lib.exceptions.ConnectionError("refused")

        with patch("requests.Session", return_value=mock_session), \
             patch("mail.factory.get_provider", return_value=self.mock_provider), \
             patch.object(self.service, "_browser_fallback", return_value=None):
            result = self.service.register("test@example.com", "passw0rd")

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
