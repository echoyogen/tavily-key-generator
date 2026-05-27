import unittest

from config import is_placeholder_env_value


class PlaceholderConfigTests(unittest.TestCase):
    def test_detects_example_placeholders(self) -> None:
        self.assertTrue(is_placeholder_env_value("EMAIL_API_URL", "https://your-mail-api.example.com"))
        self.assertTrue(is_placeholder_env_value("EMAIL_API_TOKEN", "replace-with-your-token"))
        self.assertTrue(is_placeholder_env_value("EMAIL_DOMAIN", "example.com"))
        self.assertTrue(is_placeholder_env_value("EMAIL_DOMAINS", "example.org"))
        self.assertTrue(is_placeholder_env_value("SERVER_URL", "https://your-server.example.com"))
        self.assertTrue(is_placeholder_env_value("SERVER_ADMIN_PASSWORD", "replace-with-your-admin-password"))

    def test_allows_real_values(self) -> None:
        self.assertFalse(is_placeholder_env_value("EMAIL_API_URL", "https://mail.nashome.me"))
        self.assertFalse(is_placeholder_env_value("EMAIL_API_TOKEN", "abc123-real-token"))
        self.assertFalse(is_placeholder_env_value("EMAIL_DOMAIN", "nashome.me"))
        self.assertFalse(is_placeholder_env_value("SERVER_URL", "https://search.hunters.works"))
        self.assertFalse(is_placeholder_env_value("SERVER_ADMIN_PASSWORD", "Jelly120425"))


class MailFactoryTests(unittest.TestCase):
    def test_selected_domain_is_module_level(self):
        import mail.factory as f
        self.assertTrue(hasattr(f, '_SELECTED_DOMAIN'), "_SELECTED_DOMAIN must be module-level")

    def test_set_domain_updates_get_active_domain(self):
        from mail.factory import set_domain, get_active_domain
        set_domain("testdomain.com")
        self.assertEqual(get_active_domain(), "testdomain.com")
        set_domain("")

    def test_validate_runtime_config_upload_without_server_url(self):
        from cli.prompts import validate_runtime_config
        import config
        original = config.SERVER_URL
        config.SERVER_URL = ""
        try:
            result = validate_runtime_config(upload=True, show_provider_summary=False)
            self.assertFalse(result, "Should return False when SERVER_URL not configured")
        finally:
            config.SERVER_URL = original


if __name__ == "__main__":
    unittest.main()
