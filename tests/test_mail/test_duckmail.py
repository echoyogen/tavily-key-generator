import unittest
import mail.duckmail as mod
from mail.duckmail import DuckMailProvider
from mail.base import MailProvider


class TestDuckMailProvider(unittest.TestCase):
    def test_no_global_cache(self):
        assert not hasattr(mod, "_DUCKMAIL_MAILBOX_CACHE"), "Cache must not be global"

    def test_instance_caches_are_independent(self):
        p1 = DuckMailProvider.__new__(DuckMailProvider)
        p1.__init__(api_url="http://x", api_key="k", domains=["a.com"])
        p2 = DuckMailProvider.__new__(DuckMailProvider)
        p2.__init__(api_url="http://x", api_key="k", domains=["a.com"])
        p1._mailbox_cache["test"] = "value"
        assert "test" not in p2._mailbox_cache, "Caches must be independent"

    def test_is_mail_provider(self):
        assert issubclass(DuckMailProvider, MailProvider)

    def test_init_sets_api_url(self):
        p = DuckMailProvider(api_url="http://example.com", api_key="key", domains=["d.com"])
        assert p._api_url == "http://example.com"

    def test_init_sets_domains(self):
        p = DuckMailProvider(api_url="http://x", api_key="k", domains=["a.com", "b.com"])
        assert "a.com" in p._domains
        assert "b.com" in p._domains

    def test_init_empty_mailbox_cache(self):
        p = DuckMailProvider(api_url="http://x", api_key="k", domains=["a.com"])
        assert isinstance(p._mailbox_cache, dict)
        assert len(p._mailbox_cache) == 0

    def test_domain_cache_starts_none(self):
        p = DuckMailProvider(api_url="http://x", api_key="k", domains=["a.com"])
        assert p._domain_cache is None


if __name__ == "__main__":
    unittest.main()
