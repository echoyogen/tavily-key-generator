"""
统一邮箱 provider 抽象。
当前支持：
1. Cloudflare 自定义邮件 API
2. DuckMail API
3. OnlineDispoMail API
"""
import html
import random
import re
import string
import threading
import time
from pathlib import Path

import requests as std_requests

from config import (
    DUCKMAIL_API_KEY,
    DUCKMAIL_API_URL,
    DUCKMAIL_DOMAIN,
    DUCKMAIL_DOMAINS,
    EMAIL_API_TOKEN,
    EMAIL_API_URL,
    EMAIL_DOMAIN,
    EMAIL_DOMAINS,
    EMAIL_POLL_INTERVAL,
    EMAIL_PROVIDER,
    ONLINEMAIL_API_KEY,
    ONLINEMAIL_BUY_MODE,
    ONLINEMAIL_MODE,
    ONLINEMAIL_ORDERS_FILE,
)

_DUCKMAIL_DOMAIN_PRIORITY = (
    "baldur.edu.kg",
    "duckmail.sbs",
)
_DUCKMAIL_DOMAIN_CACHE = None
_DUCKMAIL_MAILBOX_CACHE = {}
_SELECTED_DOMAIN = ""
_SUPPORTED_SERVICES = ("tavily", "firecrawl", "exa", "you", "serper", "valyu")

_ONLINEMAIL_API_BASE = "https://api.online-disposablemail.com/api"
_ONLINEMAIL_SERVICE_MAP = {
    "exa": {"service_id": "261", "email_type_id": "26"},
    "you": {"service_id": "262", "email_type_id": "26"},
}
_ONLINEMAIL_UNSUPPORTED = frozenset({"tavily", "firecrawl", "serper", "valyu"})
_ONLINEMAIL_MAILBOX_CACHE = {}
_ONLINEMAIL_FILE_LOCK = threading.Lock()



def _onlinemail_file_pop(service):
    path = ONLINEMAIL_ORDERS_FILE
    with _ONLINEMAIL_FILE_LOCK:
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
        Path(path).write_text("\n".join(remaining) + ("\n" if remaining else ""), encoding="utf-8")

    parts = consumed.split("----", 1)
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        raise RuntimeError(
            f"OnlineDispoMail orders file: invalid line format '{consumed}'\n"
            "Expected: email----orderId"
        )
    email, order_id = parts[0].strip(), parts[1].strip()
    return email, order_id


def _onlinemail_api_purchase(service):
    service_norm = _normalize_service(service)
    mapping = _ONLINEMAIL_SERVICE_MAP.get(service_norm)
    if not mapping:
        raise RuntimeError(
            f"OnlineDispoMail does not support service '{service_norm}'. "
            f"Supported: {', '.join(sorted(_ONLINEMAIL_SERVICE_MAP))}"
        )
    params = {
        "apiKey": ONLINEMAIL_API_KEY,
        "serviceId": mapping["service_id"],
        "emailTypeId": mapping["email_type_id"],
        "quantity": "1",
        "buyMode": ONLINEMAIL_BUY_MODE,
        "linkPriority": "false",
    }
    response = std_requests.get(
        f"{_ONLINEMAIL_API_BASE}/mailbox",
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


def _create_onlinemail_mailbox(service):
    service_norm = _normalize_service(service)
    if service_norm in _ONLINEMAIL_UNSUPPORTED:
        raise RuntimeError(
            f"OnlineDispoMail does not support service '{service_norm}'. "
            f"Use a different EMAIL_PROVIDER for this service."
        )

    if ONLINEMAIL_MODE == "api":
        email, order_id = _onlinemail_api_purchase(service_norm)
    else:
        email, order_id = _onlinemail_file_pop(service_norm)

    _ONLINEMAIL_MAILBOX_CACHE[email] = {"order_id": order_id}
    return email


def _onlinemail_iter_messages(email):
    mailbox = _ONLINEMAIL_MAILBOX_CACHE.get(email)
    if not mailbox:
        raise RuntimeError(
            "OnlineDispoMail mailbox context not found. "
            "Re-generate the email address before polling."
        )
    order_id = mailbox["order_id"]
    response = std_requests.get(
        f"{_ONLINEMAIL_API_BASE}/latest/code",
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


def rand_str(n=8):
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))

def get_configured_domains():
    """返回当前 provider 在配置里声明的可选域名。"""
    if EMAIL_PROVIDER == "duckmail":
        return DUCKMAIL_DOMAINS[:]
    return EMAIL_DOMAINS[:]

def get_active_domain():
    """返回当前实际使用的域名。"""
    if _SELECTED_DOMAIN:
        return _SELECTED_DOMAIN

    configured = get_configured_domains()
    if configured:
        return configured[0]

    if EMAIL_PROVIDER == "duckmail":
        return DUCKMAIL_DOMAIN
    return EMAIL_DOMAIN

def set_selected_domain(domain):
    """设置本轮运行使用的域名。"""
    global _SELECTED_DOMAIN
    _SELECTED_DOMAIN = (domain or "").strip()


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
    """按当前 provider 生成邮箱与强密码。"""
    password = f"Tv{rand_str(6)}{random.randint(100, 999)}!A"
    prefix = _username_prefix(service)

    if EMAIL_PROVIDER == "duckmail":
        email = _create_duckmail_mailbox(password, prefix)
    elif EMAIL_PROVIDER == "onlinemail":
        email = _create_onlinemail_mailbox(service)
        password = ""
    else:
        username = f"{prefix}-{rand_str()}"
        email = f"{username}@{get_active_domain()}"

    print(f"✅ 邮箱({EMAIL_PROVIDER}): {email}")
    return email, password


def get_verification_link(email, timeout=120):
    """等待验证邮件并提取验证链接。"""
    print(f"⏳ 等待验证邮件（最多 {timeout} 秒）...", end="", flush=True)
    return _poll_mailbox(
        email=email,
        timeout=timeout,
        extractor=_extract_verification_link,
        found_message="\n✅ 找到验证链接",
        timeout_message="\n❌ 验证邮件超时",
        error_prefix="检查验证邮件失败",
        dot_progress=True,
    )


def get_email_code(email, timeout=120, service="tavily"):
    """等待邮箱里的 6 位验证码。"""
    print(f"📨 等待邮箱验证码（最多 {timeout} 秒）...")
    return _poll_mailbox(
        email=email,
        timeout=timeout,
        extractor=lambda message: _extract_email_code(message, service=service),
        found_message="✅ 收到 6 位验证码",
        timeout_message="❌ 等待邮箱验证码超时",
        error_prefix="读取邮箱验证码失败",
        dot_progress=False,
    )


def _poll_mailbox(email, timeout, extractor, found_message, timeout_message, error_prefix, dot_progress):
    start_time = time.time()
    seen_ids = set()

    while time.time() - start_time < timeout:
        try:
            for message in _iter_messages(email):
                message_id = _message_id(message)
                if message_id and message_id in seen_ids:
                    continue
                if message_id:
                    seen_ids.add(message_id)

                result = extractor(message)
                if result:
                    print(found_message)
                    return result
        except Exception as exc:
            print(f"⚠️  {error_prefix}: {exc}")

        time.sleep(EMAIL_POLL_INTERVAL)
        if dot_progress:
            print(".", end="", flush=True)

    print(timeout_message)
    return None


def _extract_verification_link(message):
    subject = (message.get("subject") or "").lower()
    sender = (message.get("from") or message.get("message_from") or "").lower()
    content = _message_content(message)
    urls = [
        html.unescape(raw).rstrip(").,;")
        for raw in re.findall(r'https://[^\s<>"\']+', content, re.IGNORECASE)
    ]

    primary_link_hints = ("verif", "confirm", "magic", "auth", "callback", "signin", "signup")
    primary_host_hints = ("tavily", "firecrawl", "clerk", "stytch", "auth", "login", "serper", "supabase")
    for url in urls:
        lowered = url.lower()
        if any(token in lowered for token in primary_link_hints) and any(host in lowered for host in primary_host_hints):
            return url

    combined = f"{sender} {subject} {content[:4000]}".lower()
    message_hints = ("verify", "verification", "confirm", "magic link", "sign in", "tavily", "firecrawl")
    if not any(token in combined for token in message_hints):
        return None

    for url in urls:
        lowered = url.lower()
        if any(token in lowered for token in primary_link_hints):
            return url

    return None


def _extract_email_code(message, service="tavily"):
    service = _normalize_service(service)
    subject = (message.get("subject") or "").lower()
    text = message.get("text") or ""
    content = _message_content(message)
    combined = f"{subject}\n{content}".lower()

    if service == "exa":
        if "exa" not in combined:
            return None
        if "verification code" not in combined and "sign in" not in combined:
            return None
        for source in (text, content):
            match = re.search(
                r"verification code(?:\s+for\s+exa)?(?:\s+is)?[^0-9]*(\d{6})",
                source,
                re.IGNORECASE,
            )
            if match:
                return match.group(1)
    elif service == "you":
        if "you.com" not in combined and "youmail" not in combined and "sign in" not in combined:
            return None
        for source in (text, content):
            match = re.search(
                r"verification code(?:\s+is)?[^0-9]*(\d{6})",
                source,
                re.IGNORECASE,
            )
            if match:
                return match.group(1)
        for source in (text, content):
            match = re.search(r"\b(\d{6})\b", source)
            if match:
                return match.group(1)
        return None
    else:
        if "verify your identity" not in subject and "verify" not in subject and "tavily" not in combined:
            return None

    for source in (text, content):
        match = re.search(r"\b(\d{6})\b", source)
        if match:
            return match.group(1)
    return None


def _iter_messages(email):
    if EMAIL_PROVIDER == "duckmail":
        yield from _duckmail_iter_messages(email)
        return
    if EMAIL_PROVIDER == "onlinemail":
        yield from _onlinemail_iter_messages(email)
        return

    yield from _cloudflare_iter_messages(email)


def _cloudflare_iter_messages(email):
    response = std_requests.get(
        f"{EMAIL_API_URL}/messages",
        params={"address": email},
        headers={"Authorization": f"Bearer {EMAIL_API_TOKEN}"},
        timeout=10,
    )
    response.raise_for_status()

    for message in response.json().get("messages", []):
        yield message


def _duckmail_iter_messages(email):
    token = _duckmail_get_token(email)
    response = _duckmail_request("GET", "/messages", token=token)

    if response.status_code == 401:
        token = _duckmail_get_token(email, refresh=True)
        response = _duckmail_request("GET", "/messages", token=token)

    response.raise_for_status()

    for message in response.json().get("hydra:member", []):
        message_id = message.get("id")
        if not message_id:
            continue

        detail = _duckmail_request("GET", f"/messages/{message_id}", token=token)
        if detail.status_code == 401:
            token = _duckmail_get_token(email, refresh=True)
            detail = _duckmail_request("GET", f"/messages/{message_id}", token=token)
        detail.raise_for_status()
        yield detail.json()


def _create_duckmail_mailbox(password, prefix):
    domain = _choose_duckmail_domain()

    for _ in range(5):
        username = f"{prefix}-{rand_str()}"
        email = f"{username}@{domain}"
        response = _duckmail_request(
            "POST",
            "/accounts",
            json={"address": email, "password": password},
            use_api_key=True,
        )

        if response.status_code == 201:
            account = response.json()
            token = _duckmail_issue_token(email, password)
            _DUCKMAIL_MAILBOX_CACHE[email] = {
                "account_id": account.get("id", ""),
                "password": password,
                "token": token,
            }
            return email

        if response.status_code not in (409, 422):
            response.raise_for_status()

        message = _response_error_message(response).lower()
        if "exists" in message or "already" in message or response.status_code == 409:
            continue

        raise RuntimeError(f"DuckMail 创建邮箱失败: {_response_error_message(response)}")

    raise RuntimeError("DuckMail 邮箱创建失败：随机地址重复次数过多")


def _choose_duckmail_domain():
    domains = _duckmail_domains()
    selected = get_active_domain()
    configured = get_configured_domains()

    if selected:
        if selected not in domains:
            raise RuntimeError(
                f"配置的 DuckMail 域名不可用: {selected}，当前可用域名: {', '.join(domains)}"
            )
        return selected

    for domain in configured:
        if domain in domains:
            return domain

    for domain in _DUCKMAIL_DOMAIN_PRIORITY:
        if domain in domains:
            return domain

    return domains[0]


def _duckmail_domains():
    global _DUCKMAIL_DOMAIN_CACHE
    if _DUCKMAIL_DOMAIN_CACHE is not None:
        return _DUCKMAIL_DOMAIN_CACHE

    response = _duckmail_request("GET", "/domains", use_api_key=True)
    response.raise_for_status()
    domains = [
        item.get("domain")
        for item in response.json().get("hydra:member", [])
        if item.get("domain")
    ]

    if not domains:
        raise RuntimeError("DuckMail 未返回可用域名")

    _DUCKMAIL_DOMAIN_CACHE = domains
    return domains


def _duckmail_get_token(email, refresh=False):
    mailbox = _DUCKMAIL_MAILBOX_CACHE.get(email)
    if not mailbox:
        raise RuntimeError("DuckMail 邮箱上下文不存在，请重新生成邮箱后再试")

    if mailbox.get("token") and not refresh:
        return mailbox["token"]

    mailbox["token"] = _duckmail_issue_token(email, mailbox["password"])
    return mailbox["token"]


def _duckmail_issue_token(email, password):
    response = _duckmail_request(
        "POST",
        "/token",
        json={"address": email, "password": password},
    )
    response.raise_for_status()

    token = response.json().get("token")
    if not token:
        raise RuntimeError("DuckMail 登录成功但未返回 token")
    return token


def _duckmail_request(method, path, token=None, use_api_key=False, **kwargs):
    headers = dict(kwargs.pop("headers", {}))
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif use_api_key and DUCKMAIL_API_KEY:
        headers["Authorization"] = f"Bearer {DUCKMAIL_API_KEY}"

    if "json" in kwargs:
        headers.setdefault("Content-Type", "application/json")

    return std_requests.request(
        method,
        f"{DUCKMAIL_API_URL.rstrip('/')}{path}",
        headers=headers,
        timeout=kwargs.pop("timeout", 15),
        **kwargs,
    )


def _message_id(message):
    return message.get("id") or message.get("msgid")


def _message_content(message):
    html = message.get("html") or ""
    if isinstance(html, list):
        html = " ".join(str(item) for item in html)
    text = message.get("text") or ""
    return f"{html} {text}"


def _response_error_message(response):
    try:
        data = response.json()
    except ValueError:
        return response.text.strip() or f"HTTP {response.status_code}"

    if isinstance(data, dict):
        return data.get("message") or data.get("detail") or data.get("error") or str(data)
    return str(data)
