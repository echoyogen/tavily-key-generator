"""
Tests for FirecrawlService HTTP-primary flow.
"""
import unittest
from unittest.mock import MagicMock, patch

from services.firecrawl.service import FirecrawlService


class TestFirecrawlServiceHttpFlow(unittest.TestCase):
    def setUp(self):
        self.service = FirecrawlService()

    def test_register_http_success(self):
        """HTTP success path: register() returns correct key, _browser_fallback not called."""
        with patch('requests.Session') as mock_session_class, \
             patch.object(self.service, '_do_post_verify'), \
             patch.object(self.service, '_save_result'), \
             patch.object(self.service, '_browser_fallback') as mock_browser:
            
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session
            
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"api_key": "fc-testkey123456789012345"}
            mock_session.post.return_value = mock_response
            
            result = self.service.register('test@example.com', 'passw0rd')
        
        self.assertEqual(result, 'fc-testkey123456789012345')
        mock_browser.assert_not_called()

    def test_register_http_fails_triggers_fallback(self):
        """HTTP fails with ConnectionError -> _browser_fallback is called."""
        with patch('requests.Session') as mock_session_class, \
             patch.object(self.service, '_browser_fallback', return_value='fc-browserkey1234567890123') as mock_browser:
            
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session
            mock_session.post.side_effect = Exception("Connection error")
            
            result = self.service.register('test@example.com', 'passw0rd')
        
        mock_browser.assert_called_once_with('test@example.com', 'passw0rd')
        self.assertEqual(result, 'fc-browserkey1234567890123')

    def test_register_both_fail_returns_none(self):
        """HTTP fails and _browser_fallback returns None -> result is None."""
        with patch('requests.Session') as mock_session_class, \
             patch.object(self.service, '_browser_fallback', return_value=None) as mock_browser:
            
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session
            mock_session.post.side_effect = Exception("Connection error")
            
            result = self.service.register('test@example.com', 'passw0rd')
        
        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
