"""
Tests for ValyuService HTTP-primary flow.
"""
import unittest
from unittest.mock import MagicMock, patch

from services.valyu.service import ValyuService, _FALLBACK_ACTION_ID


class TestValyuServiceHttpPrimary(unittest.TestCase):
    def setUp(self):
        self.service = ValyuService()
        self.mock_provider = MagicMock()
        self.mock_provider.get_existing_message_ids.return_value = set()
        self.mock_provider.get_verification_link.return_value = 'https://auth.valyu.ai/auth/v1/verify?token=abc123'

    def test_register_http_success(self):
        """HTTP success path: register() returns correct key, _browser_fallback not called."""
        with patch('mail.factory.get_provider', return_value=self.mock_provider), \
             patch.object(self.service, '_warm_up'), \
             patch.object(self.service, '_submit_onboarding', return_value=True), \
             patch.object(self.service, '_verify_via_link', return_value=True), \
             patch.object(self.service, '_password_login', return_value='tok_test123'), \
             patch.object(self.service, '_fetch_api_key_http', return_value='valyu_testkey12345678901234'), \
             patch.object(self.service, '_do_post_verify'), \
             patch.object(self.service, '_save_result'), \
             patch('time.sleep'), \
             patch.object(self.service, '_browser_fallback') as mock_browser:
            result = self.service.register('test@example.com', 'Pass123!')

        self.assertEqual(result, 'valyu_testkey12345678901234')
        mock_browser.assert_not_called()

    def test_register_fallbacks_to_browser_when_onboarding_fails(self):
        """Both onboarding and supabase fail -> _browser_fallback is called."""
        with patch('mail.factory.get_provider', return_value=self.mock_provider), \
             patch.object(self.service, '_warm_up'), \
             patch.object(self.service, '_submit_onboarding', return_value=False), \
             patch.object(self.service, '_supabase_signup_fallback', return_value=False), \
             patch.object(self.service, '_browser_fallback', return_value='valyu_browserfallbackkey12345678') as mock_browser:
            result = self.service.register('test@example.com', 'Pass123!')

        mock_browser.assert_called_once_with('test@example.com', 'Pass123!')
        self.assertEqual(result, 'valyu_browserfallbackkey12345678')

    def test_register_fallbacks_to_browser_when_token_is_none(self):
        """_password_login returns None -> _browser_fallback is called."""
        with patch('mail.factory.get_provider', return_value=self.mock_provider), \
             patch.object(self.service, '_warm_up'), \
             patch.object(self.service, '_submit_onboarding', return_value=True), \
             patch.object(self.service, '_verify_via_link', return_value=True), \
             patch.object(self.service, '_password_login', return_value=None), \
             patch.object(self.service, '_browser_fallback', return_value=None) as mock_browser, \
             patch('time.sleep'):
            result = self.service.register('test@example.com', 'Pass123!')

        mock_browser.assert_called_once()
        self.assertIsNone(result)

    def test_register_fallbacks_to_browser_on_unexpected_exception(self):
        """_warm_up raises Exception -> _browser_fallback is called."""
        with patch('mail.factory.get_provider', return_value=self.mock_provider), \
             patch.object(self.service, '_warm_up', side_effect=RuntimeError('connection error')), \
             patch.object(self.service, '_browser_fallback', return_value='valyu_key12345678901234567890') as mock_browser:
            result = self.service.register('test@example.com', 'Pass123!')

        mock_browser.assert_called_once()
        self.assertEqual(result, 'valyu_key12345678901234567890')


class TestValyuServiceNextAction(unittest.TestCase):
    def setUp(self):
        self.service = ValyuService()

    def test_dynamic_next_action_extracted_from_html(self):
        """HTML contains $ACTION_1:0 value -> returns correct action_id (no fallback)."""
        import html as html_lib
        import json

        action_id = 'abcdef1234567890abcdef1234567890abcdef1234'
        action_data = json.dumps({"id": action_id, "bound": "$@1"})
        encoded = html_lib.escape(action_data)
        html_content = f'<input name="$ACTION_1:0" value="{encoded}">'

        mock_sess = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = html_content
        mock_sess.get.return_value = mock_resp

        _, extracted_id = self.service._get_onboarding_page_html(mock_sess, 'test@example.com')
        self.assertEqual(extracted_id, action_id)

    def test_fallback_action_id_used_when_no_match(self):
        """HTML has no action data -> returns _FALLBACK_ACTION_ID."""
        mock_sess = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = '<html><body>no action here</body></html>'
        mock_sess.get.return_value = mock_resp

        _, extracted_id = self.service._get_onboarding_page_html(mock_sess, 'test@example.com')
        self.assertEqual(extracted_id, _FALLBACK_ACTION_ID)


class TestValyuServiceExtractKey(unittest.TestCase):
    def setUp(self):
        self.service = ValyuService()

    def test_extract_valyu_key_found(self):
        """Text contains valyu_xxx format -> returns matched value."""
        text = 'some content valyu_k8mNpQrStUvWxYz1234567890 more content'
        key = self.service._extract_valyu_key(text)
        self.assertIsNotNone(key)
        self.assertTrue(key.startswith('valyu_'))
        self.assertEqual(key, 'valyu_k8mNpQrStUvWxYz1234567890')

    def test_extract_valyu_key_not_found(self):
        """Text has no valyu key -> returns None."""
        text = 'some random content without any api key'
        key = self.service._extract_valyu_key(text)
        self.assertIsNone(key)


class TestValyuServiceImports(unittest.TestCase):
    def test_module_imports(self):
        """Module imports without exception, key constants accessible."""
        from services.valyu.service import ValyuService, SUPABASE_URL, SUPABASE_ANON_KEY
        self.assertIsNotNone(ValyuService)
        self.assertIsNotNone(SUPABASE_URL)
        self.assertIsNotNone(SUPABASE_ANON_KEY)

    def test_class_attributes(self):
        """Class attributes have correct values."""
        service = ValyuService()
        self.assertEqual(service.name, "valyu")
        self.assertEqual(service.signup_url, "https://platform.valyu.ai/auth")
        self.assertEqual(service.output_file, "valyu_accounts.txt")


if __name__ == '__main__':
    unittest.main()
