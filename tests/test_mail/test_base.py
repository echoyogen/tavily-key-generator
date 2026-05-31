import unittest
from unittest.mock import patch
from mail.base import MailProvider


class MockProvider(MailProvider):
    def __init__(self, messages):
        self._messages = messages

    def create_mailbox(self, prefix, domain=None):
        return f"{prefix}@test.com", "pass"

    def get_messages(self, email):
        return iter(self._messages)


class TestMailProviderBase(unittest.TestCase):
    def test_get_verification_link_finds_link(self):
        msg = {
            "subject": "verify your email",
            "html": "Click https://clerk.com/verify?token=abc123",
            "text": "",
        }
        provider = MockProvider([msg])
        with patch("time.sleep"):
            link = provider.get_verification_link("test@test.com", timeout=5)
        assert link is not None
        assert "verify" in link.lower() or "clerk" in link.lower()

    def test_get_verification_link_timeout(self):
        provider = MockProvider([])
        with patch("time.sleep"):
            link = provider.get_verification_link("test@test.com", timeout=1)
        assert link is None

    def test_get_email_code_exa(self):
        msg = {
            "subject": "verification code",
            "text": "Your verification code for exa is 123456",
            "html": "",
        }
        provider = MockProvider([msg])
        with patch("time.sleep"):
            code = provider.get_email_code("test@test.com", timeout=5, service_hint="exa")
        assert code == "123456"

    def test_get_email_code_timeout(self):
        provider = MockProvider([])
        with patch("time.sleep"):
            code = provider.get_email_code("test@test.com", timeout=1)
        assert code is None

    def test_get_verification_link_skips_seen_messages(self):
        msg = {
            "id": "msg-001",
            "subject": "verify your email",
            "html": "Click https://clerk.com/verify?token=abc123",
            "text": "",
        }
        call_count = [0]
        original_get_messages = MockProvider.get_messages

        class CountingProvider(MockProvider):
            def get_messages(self, email):
                call_count[0] += 1
                return iter([msg])

        provider = CountingProvider([msg])
        with patch("time.sleep"):
            link = provider.get_verification_link("test@test.com", timeout=5)
        assert link is not None

    def test_extract_verification_link_no_match_returns_none(self):
        msg = {
            "subject": "welcome to our service",
            "html": "Hello there, no links here",
            "text": "",
        }
        provider = MockProvider([msg])
        with patch("time.sleep"):
            link = provider.get_verification_link("test@test.com", timeout=1)
        assert link is None

    def test_get_email_code_you_service(self):
        msg = {
            "subject": "sign in to you.com",
            "text": "verification code is 654321",
            "html": "",
        }
        provider = MockProvider([msg])
        with patch("time.sleep"):
            code = provider.get_email_code("test@test.com", timeout=5, service_hint="you")
        assert code == "654321"


if __name__ == "__main__":
    unittest.main()
