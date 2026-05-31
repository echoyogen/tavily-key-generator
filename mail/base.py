import html
import re
import time
from abc import ABC, abstractmethod

EMAIL_POLL_INTERVAL = 3

_SUPPORTED_SERVICES = ("tavily", "firecrawl", "exa", "you", "serper", "valyu")


def _normalize_service(service):
    service = (service or "tavily").strip().lower()
    if service not in _SUPPORTED_SERVICES:
        return "tavily"
    return service


class MailProvider(ABC):

    @abstractmethod
    def create_mailbox(self, prefix, domain=None):
        pass

    @abstractmethod
    def get_messages(self, email):
        pass

    def get_verification_link(self, email, timeout=120):
        print(f"⏳ 等待验证邮件（最多 {timeout} 秒）...", end="", flush=True)
        return self._poll_mailbox(
            email=email,
            timeout=timeout,
            extractor=self._extract_verification_link,
            found_message="\n✅ 找到验证链接",
            timeout_message="\n❌ 验证邮件超时",
            error_prefix="检查验证邮件失败",
            dot_progress=True,
        )

    def get_email_code(self, email, timeout=120, service_hint="tavily", skip_ids=None):
        print(f"📨 等待邮箱验证码（最多 {timeout} 秒）...")
        return self._poll_mailbox(
            email=email,
            timeout=timeout,
            extractor=lambda message: self._extract_email_code(message, service_hint=service_hint),
            found_message="✅ 收到 6 位验证码",
            timeout_message="❌ 等待邮箱验证码超时",
            error_prefix="读取邮箱验证码失败",
            dot_progress=False,
            skip_ids=skip_ids,
        )

    def get_existing_message_ids(self, email) -> set:
        """返回当前邮箱里所有已存在的消息 ID，用于之后跳过旧邮件"""
        try:
            return {self._message_id(m) for m in self.get_messages(email) if self._message_id(m)}
        except Exception:
            return set()

    def _poll_mailbox(self, email, timeout, extractor, found_message, timeout_message, error_prefix, dot_progress, skip_ids=None):
        start_time = time.time()
        seen_ids = set(skip_ids) if skip_ids else set()

        while time.time() - start_time < timeout:
            try:
                for message in self.get_messages(email):
                    message_id = self._message_id(message)
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

    def _extract_verification_link(self, message):
        subject = (message.get("subject") or "").lower()
        sender = (message.get("from") or message.get("message_from") or "").lower()
        content = self._message_content(message)
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

    def _extract_email_code(self, message, service_hint="tavily"):
        service = _normalize_service(service_hint)
        subject = (message.get("subject") or "").lower()
        text = message.get("text") or ""
        content = self._message_content(message)
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
                    r"(?:verification|login|one-time)\s+code(?:\s+is)?[^0-9]*(\d{6})",
                    source,
                    re.IGNORECASE,
                )
                if match:
                    return match.group(1)
            for source in (text, content):
                # exclude CSS color values like #101012
                match = re.search(r"(?<!#)\b(\d{6})\b", source)
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

    def _message_id(self, message):
        return message.get("id") or message.get("msgid")

    def _message_content(self, message):
        html_content = message.get("html") or ""
        if isinstance(html_content, list):
            html_content = " ".join(str(item) for item in html_content)
        text = message.get("text") or ""
        return f"{html_content} {text}"
