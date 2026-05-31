import unittest
from mail.cloudflare import CloudflareProvider
from mail.base import MailProvider


class TestCloudflareProvider(unittest.TestCase):
    def setUp(self):
        self.provider = CloudflareProvider(
            api_url="https://api.example.com",
            api_token="test-token",
            domain="example.com",
        )

    def test_is_mail_provider(self):
        assert isinstance(self.provider, MailProvider)

    def test_create_mailbox_format(self):
        email, pw = self.provider.create_mailbox("test")
        assert "@example.com" in email
        assert email.startswith("test-")

    def test_create_mailbox_custom_domain(self):
        email, pw = self.provider.create_mailbox("test", domain="other.com")
        assert "@other.com" in email

    def test_create_mailbox_returns_empty_password(self):
        email, pw = self.provider.create_mailbox("user")
        assert pw == ""

    def test_create_mailbox_unique_emails(self):
        email1, _ = self.provider.create_mailbox("user")
        email2, _ = self.provider.create_mailbox("user")
        assert email1 != email2

    def test_create_mailbox_prefix_in_email(self):
        email, _ = self.provider.create_mailbox("myprefix")
        local_part = email.split("@")[0]
        assert local_part.startswith("myprefix-")


if __name__ == "__main__":
    unittest.main()
