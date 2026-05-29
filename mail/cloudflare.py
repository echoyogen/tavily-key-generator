import random
import string

import requests

from mail.base import MailProvider


def _rand_str(n=8):
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


class CloudflareProvider(MailProvider):

    def __init__(self, api_url, api_token, domain):
        self._api_url = api_url
        self._api_token = api_token
        self._domain = domain

    def create_mailbox(self, username, domain=None):
        target_domain = domain or self._domain
        email = f"{username}@{target_domain}"
        return email, ""

    def get_messages(self, email):
        response = requests.get(
            f"{self._api_url}/messages",
            params={"address": email},
            headers={"Authorization": f"Bearer {self._api_token}"},
            timeout=10,
        )
        response.raise_for_status()
        for message in response.json().get("messages", []):
            yield message
