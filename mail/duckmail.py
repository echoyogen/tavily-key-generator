import random
import string

import requests as std_requests

from mail.base import MailProvider

_DUCKMAIL_DOMAIN_PRIORITY = (
    "baldur.edu.kg",
    "duckmail.sbs",
)


def _rand_str(n=8):
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def _response_error_message(response):
    try:
        data = response.json()
    except ValueError:
        return response.text.strip() or f"HTTP {response.status_code}"

    if isinstance(data, dict):
        return data.get("message") or data.get("detail") or data.get("error") or str(data)
    return str(data)


class DuckMailProvider(MailProvider):

    def __init__(self, api_url, api_key, domains):
        self._api_url = api_url
        self._api_key = api_key
        self._domains = domains
        self._mailbox_cache = {}
        self._domain_cache = None
        self._token_cache = {}

    def create_mailbox(self, prefix, domain=None):
        password = _rand_str(16)
        chosen_domain = domain or self._choose_domain()

        for _ in range(5):
            username = f"{prefix}-{_rand_str()}"
            email = f"{username}@{chosen_domain}"
            response = self._request(
                "POST",
                "/accounts",
                json={"address": email, "password": password},
                use_api_key=True,
            )

            if response.status_code == 201:
                account = response.json()
                token = self._issue_token(email, password)
                self._mailbox_cache[email] = {
                    "account_id": account.get("id", ""),
                    "password": password,
                    "token": token,
                }
                return email, password

            if response.status_code not in (409, 422):
                response.raise_for_status()

            message = _response_error_message(response).lower()
            if "exists" in message or "already" in message or response.status_code == 409:
                continue

            raise RuntimeError(f"DuckMail 创建邮箱失败: {_response_error_message(response)}")

        raise RuntimeError("DuckMail 邮箱创建失败：随机地址重复次数过多")

    def get_messages(self, email):
        token = self._get_token(email)
        response = self._request("GET", "/messages", token=token)

        if response.status_code == 401:
            token = self._get_token(email, refresh=True)
            response = self._request("GET", "/messages", token=token)

        response.raise_for_status()

        for message in response.json().get("hydra:member", []):
            message_id = message.get("id")
            if not message_id:
                continue

            detail = self._request("GET", f"/messages/{message_id}", token=token)
            if detail.status_code == 401:
                token = self._get_token(email, refresh=True)
                detail = self._request("GET", f"/messages/{message_id}", token=token)
            detail.raise_for_status()
            yield detail.json()

    def _choose_domain(self):
        domains = self._fetch_available_domains()

        for domain in self._domains:
            if domain in domains:
                return domain

        for domain in _DUCKMAIL_DOMAIN_PRIORITY:
            if domain in domains:
                return domain

        return domains[0]

    def _fetch_available_domains(self):
        if self._domain_cache is not None:
            return self._domain_cache

        response = self._request("GET", "/domains", use_api_key=True)
        response.raise_for_status()
        domains = [
            item.get("domain")
            for item in response.json().get("hydra:member", [])
            if item.get("domain")
        ]

        if not domains:
            raise RuntimeError("DuckMail 未返回可用域名")

        self._domain_cache = domains
        return domains

    def _get_token(self, email, refresh=False):
        mailbox = self._mailbox_cache.get(email)
        if not mailbox:
            raise RuntimeError("DuckMail 邮箱上下文不存在，请重新生成邮箱后再试")

        if mailbox.get("token") and not refresh:
            return mailbox["token"]

        mailbox["token"] = self._issue_token(email, mailbox["password"])
        return mailbox["token"]

    def _issue_token(self, email, password):
        response = self._request(
            "POST",
            "/token",
            json={"address": email, "password": password},
        )
        response.raise_for_status()

        token = response.json().get("token")
        if not token:
            raise RuntimeError("DuckMail 登录成功但未返回 token")
        return token

    def _request(self, method, path, token=None, use_api_key=False, **kwargs):
        headers = dict(kwargs.pop("headers", {}))
        if token:
            headers["Authorization"] = f"Bearer {token}"
        elif use_api_key and self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        if "json" in kwargs:
            headers.setdefault("Content-Type", "application/json")

        return std_requests.request(
            method,
            f"{self._api_url.rstrip('/')}{path}",
            headers=headers,
            timeout=kwargs.pop("timeout", 15),
            **kwargs,
        )
