import random
import string

import config
from mail.cloudflare import CloudflareProvider
from mail.duckmail import DuckMailProvider
from mail.onlinemail import OnlineMailProvider

_SELECTED_DOMAIN = ""
_PROVIDER_INSTANCE = None

_SUPPORTED_SERVICES = ("tavily", "firecrawl", "exa", "you", "serper", "valyu")


def set_domain(domain):
    global _SELECTED_DOMAIN
    _SELECTED_DOMAIN = (domain or "").strip()


def get_active_domain():
    if _SELECTED_DOMAIN:
        return _SELECTED_DOMAIN

    configured = get_configured_domains()
    if configured:
        return configured[0]

    if config.EMAIL_PROVIDER == "duckmail":
        return config.DUCKMAIL_DOMAIN
    return config.EMAIL_DOMAIN


def get_configured_domains():
    if config.EMAIL_PROVIDER == "duckmail":
        return config.DUCKMAIL_DOMAINS[:]
    return config.EMAIL_DOMAINS[:]


def get_provider():
    global _PROVIDER_INSTANCE
    provider = config.EMAIL_PROVIDER
    domain = get_active_domain()

    # OnlineMailProvider must be a singleton so _mailbox_cache is shared between
    # create_email() (which populates it) and _verify_email() (which reads it).
    if provider == "onlinemail":
        if _PROVIDER_INSTANCE is None:
            _PROVIDER_INSTANCE = OnlineMailProvider(
                api_url="https://api.online-disposablemail.com/api",
                api_key=config.ONLINEMAIL_API_KEY,
                orders_file=config.ONLINEMAIL_ORDERS_FILE,
                mode=config.ONLINEMAIL_MODE,
            )
        return _PROVIDER_INSTANCE

    if provider == "duckmail":
        return DuckMailProvider(
            api_url=config.DUCKMAIL_API_URL,
            api_key=config.DUCKMAIL_API_KEY,
            domains=config.DUCKMAIL_DOMAINS[:],
        )

    return CloudflareProvider(
        api_url=config.EMAIL_API_URL,
        api_token=config.EMAIL_API_TOKEN,
        domain=domain,
    )


def _rand_str(n=8):
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def _normalize_service(service):
    service = (service or "tavily").strip().lower()
    if service not in _SUPPORTED_SERVICES:
        return "tavily"
    return service


def _username_prefix(service):
    service = _normalize_service(service)
    if service == "firecrawl":
        return "fc"
    if service == "exa":
        return "exa"
    if service == "you":
        return "you"
    if service == "serper":
        return "serper"
    if service == "valyu":
        return "valyu"
    return "tavily"


def create_email(service="tavily"):
    password = f"Tv{_rand_str(6)}{random.randint(100, 999)}!A"
    prefix = _username_prefix(service)
    provider = get_provider()

    if config.EMAIL_PROVIDER == "onlinemail":
        email, _ = provider.create_mailbox(prefix)
        password = ""
    else:
        email, pw = provider.create_mailbox(prefix)
        if pw:
            password = pw

    print(f"✅ 邮箱({config.EMAIL_PROVIDER}): {email}")
    return email, password
