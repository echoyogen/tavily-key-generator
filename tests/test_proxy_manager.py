"""
Tests for ProxyManager class.
"""
import threading
import pytest
from proxy_manager import ProxyManager, get_proxy_dict


class TestProxyManagerRoundRobin:
    """Test round-robin proxy selection."""

    def test_round_robin_order(self):
        """Test that proxies are returned in round-robin order."""
        m = ProxyManager(['http://a:1', 'http://b:2', 'http://c:3'])
        results = [m.get_next()['server'] for _ in range(6)]
        assert results == [
            'http://a:1',
            'http://b:2',
            'http://c:3',
            'http://a:1',
            'http://b:2',
            'http://c:3'
        ]


class TestProxyManagerThreadSafety:
    """Test thread safety of ProxyManager."""

    def test_thread_safety(self):
        """Test that ProxyManager is thread-safe with concurrent access."""
        m = ProxyManager(['http://a:1', 'http://b:2'])
        results = []
        lock = threading.Lock()

        def worker():
            for _ in range(50):
                result = m.get_next()
                with lock:
                    results.append(result)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 500
        valid_servers = {'http://a:1', 'http://b:2'}
        assert all(r['server'] in valid_servers for r in results)


class TestProxyManagerValidation:
    """Test ProxyManager validation."""

    def test_empty_list_raises(self):
        """Test that empty proxy list raises ValueError."""
        with pytest.raises(ValueError):
            ProxyManager([])


class TestProxyManagerCredentials:
    """Test credential parsing and URL decoding."""

    def test_url_decode_credentials(self):
        """Test that special characters in credentials are URL-decoded."""
        m = ProxyManager(['socks5://user:p%40ss@1.2.3.4:1080'])
        d = m.get_next()
        assert d['server'] == 'socks5://1.2.3.4:1080'
        assert d['username'] == 'user'
        assert d['password'] == 'p@ss'

    def test_no_auth_proxy(self):
        """Test that proxy without auth only returns server key."""
        m = ProxyManager(['http://1.2.3.4:8080'])
        d = m.get_next()
        assert d == {'server': 'http://1.2.3.4:8080'}
        assert 'username' not in d
        assert 'password' not in d


class TestGetProxyDict:
    """Test get_proxy_dict function."""

    def test_get_proxy_dict_disabled(self):
        """Test that get_proxy_dict returns None when manager is disabled."""
        import proxy_manager
        original = proxy_manager._manager
        try:
            proxy_manager._manager = None
            result = get_proxy_dict()
            assert result is None
        finally:
            proxy_manager._manager = original
