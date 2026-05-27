"""
Thread-safe round-robin proxy manager.
Parses proxy URLs and provides credentials in Camoufox-compatible format.
"""
import logging
import threading
from urllib.parse import ParseResult, urlparse, unquote

import config

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class ProxyManager:
    """Thread-safe round-robin proxy manager."""

    _proxies: list[ParseResult]
    _lock: threading.Lock
    _index: int

    def __init__(self, proxy_urls: list[str]) -> None:
        """
        Initialize ProxyManager with a list of proxy URLs.

        Args:
            proxy_urls: List of proxy URLs (e.g., ['http://user:pass@host:port'])

        Raises:
            ValueError: If proxy_urls is empty.
        """
        if not proxy_urls:
            raise ValueError("PROXY_LIST is empty")

        self._proxies = []
        for url in proxy_urls:
            parsed = urlparse(url)
            self._proxies.append(parsed)

        self._lock = threading.Lock()
        self._index = 0

    def get_next(self) -> dict[str, str]:
        """
        Get the next proxy in round-robin order.

        Returns:
            Dictionary with keys:
            - 'server': scheme://host:port (required)
            - 'username': decoded username (optional)
            - 'password': decoded password (optional)
        """
        with self._lock:
            parsed = self._proxies[self._index]
            self._index = (self._index + 1) % len(self._proxies)

        # Build server URL (scheme://host:port)
        if parsed.port:
            server = f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
        else:
            server = f"{parsed.scheme}://{parsed.hostname}"

        result = {"server": server}

        # Add username if present
        if parsed.username:
            result["username"] = unquote(parsed.username)

        # Add password if present
        if parsed.password:
            result["password"] = unquote(parsed.password)

        # Log only the server part (no credentials)
        logger.debug(f"Proxy selected: {server}")

        return result


# Global singleton manager
_manager = None

if config.PROXY_ENABLED:
    if config.PROXY_LIST:
        _manager = ProxyManager(config.PROXY_LIST)
    else:
        raise ValueError("PROXY_ENABLED is True but PROXY_LIST is empty")


def get_proxy_dict() -> dict[str, str] | None:
    """
    Get the next proxy dictionary from the global manager.

    Returns:
        Proxy dictionary in Camoufox format, or None if proxies are disabled.
    """
    if _manager is None:
        return None
    return _manager.get_next()
