import threading
from pathlib import Path

import requests

from mail.base import MailProvider

_ONLINEMAIL_API_BASE = "https://api.online-disposablemail.com/api"
_ONLINEMAIL_SERVICE_MAP = {
    "exa": {"service_id": "261", "email_type_id": "26"},
    "you": {"service_id": "262", "email_type_id": "26"},
}
_ONLINEMAIL_UNSUPPORTED = frozenset({"tavily", "firecrawl", "serper", "valyu"})


class OnlineMailProvider(MailProvider):

    def __init__(self, api_url, api_key, orders_file, mode):
        self._api_url = api_url or _ONLINEMAIL_API_BASE
        self._api_key = api_key
        self._orders_file = orders_file
        self._mode = mode
        self._mailbox_cache = {}
        self._file_lock = threading.Lock()

    def create_mailbox(self, prefix, domain=None):
        service = prefix
        if service in _ONLINEMAIL_UNSUPPORTED:
            raise RuntimeError(
                f"OnlineDispoMail does not support service '{service}'. "
                "Use a different EMAIL_PROVIDER for this service."
            )

        if self._mode == "api":
            email, order_id = self._api_purchase(service)
        else:
            email, order_id = self._file_pop(service)

        self._mailbox_cache[email] = {"order_id": order_id}
        return email, ""

    def get_messages(self, email):
        mailbox = self._mailbox_cache.get(email)
        if not mailbox:
            raise RuntimeError(
                "OnlineDispoMail mailbox context not found. "
                "Re-generate the email address before polling."
            )
        order_id = mailbox["order_id"]
        response = requests.get(
            f"{self._api_url}/latest/code",
            params={"orderId": order_id},
            timeout=15,
        )
        response.raise_for_status()
        body = response.json()
        biz_code = body.get("code")

        if biz_code != 200:
            msg = (body.get("msg") or "").lower()
            terminal_keywords = ("closed", "timed out", "timeout", "not found", "no longer valid")
            if any(kw in msg for kw in terminal_keywords):
                raise RuntimeError(
                    f"OnlineDispoMail order terminal error: code={biz_code} msg={body.get('msg')}"
                )
            return

        inner = body.get("data") or {}
        code_str = (inner.get("code") or "").strip()
        content_html = (inner.get("content") or "").strip()

        yield {
            "subject": "",
            "from": "",
            "html": content_html,
            "text": code_str,
        }

    def _file_pop(self, service):
        path = self._orders_file
        with self._file_lock:
            try:
                lines = Path(path).read_text(encoding="utf-8").splitlines()
            except FileNotFoundError:
                raise RuntimeError(
                    f"OnlineDispoMail orders file not found: {path}\n"
                    "Create the file with lines in format: email----orderId"
                )
            non_empty = [l.strip() for l in lines if l.strip()]
            if not non_empty:
                raise RuntimeError(
                    f"OnlineDispoMail orders file is exhausted: {path}\n"
                    "Please add more email----orderId pairs to the file."
                )
            consumed, remaining = non_empty[0], non_empty[1:]
            Path(path).write_text(
                "\n".join(remaining) + ("\n" if remaining else ""),
                encoding="utf-8",
            )

        parts = consumed.split("----", 1)
        if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
            raise RuntimeError(
                f"OnlineDispoMail orders file: invalid line format '{consumed}'\n"
                "Expected: email----orderId"
            )
        email, order_id = parts[0].strip(), parts[1].strip()
        return email, order_id

    def _api_purchase(self, service):
        mapping = _ONLINEMAIL_SERVICE_MAP.get(service)
        if not mapping:
            raise RuntimeError(
                f"OnlineDispoMail does not support service '{service}'. "
                f"Supported: {', '.join(sorted(_ONLINEMAIL_SERVICE_MAP))}"
            )
        params = {
            "apiKey": self._api_key,
            "serviceId": mapping["service_id"],
            "emailTypeId": mapping["email_type_id"],
            "quantity": "1",
            "buyMode": "0",
            "linkPriority": "false",
        }
        response = requests.get(
            f"{self._api_url}/mailbox",
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("code") != 200:
            raise RuntimeError(
                f"OnlineDispoMail purchase failed: code={data.get('code')} msg={data.get('msg')}"
            )
        orders = (data.get("data") or {}).get("orders") or []
        if not orders:
            raise RuntimeError("OnlineDispoMail API returned empty orders list")
        first = orders[0]
        email = (first.get("email") or "").strip()
        order_id = (first.get("orderId") or "").strip()
        if not email or not order_id:
            raise RuntimeError(
                f"OnlineDispoMail API returned invalid order: email={email!r}, orderId={order_id!r}"
            )
        return email, order_id
