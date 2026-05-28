"""
YouService — 纯 HTTP 逆向实现（无浏览器）

认证链路：
  1. POST auth.you.com/v1/auth/otp/signup/email  (新账号) 或
     POST auth.you.com/v1/auth/otp/signin/email  (已有账号)
       Authorization: Bearer <DESCOPE_PROJECT_ID>
       body: {"loginId": "<email>"}
       → 触发 OTP 邮件发送

  2. 读取 OTP 邮件验证码（通过 mail provider）

  3. POST auth.you.com/v1/auth/otp/verify/email
       Authorization: Bearer <DESCOPE_PROJECT_ID>
       body: {"loginId": "<email>", "code": "<otp>"}
       → Set-Cookie: DS=...; DSR=...（自动注入 sess.cookies）

  4. GET you.com/platform/api-keys
       → 提取 Next.js Server Action 参数（$ACTION_1:0、$ACTION_KEY 等）

  5. POST you.com/platform/api-keys  (multipart/form-data + Next-Action header)
       → RSC payload，从中提取 ydc-sk-... 格式的 API key
"""

import html as _html_mod
import re
import time

import requests

import config
from services.base import BaseService


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
DESCOPE_PROJECT_ID = "P2jInttRMuXpyYZMbVcsc4C9Z0RT"
DESCOPE_BASE = "https://auth.you.com"

# Server Action ID（基于 you.com 代码 hash，版本固定时不变）
_SERVER_ACTION_ID = "60181fa620faa693db04894fec1c5433ba0a327c76"

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"

_NAV_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "user-agent": _UA,
}

_DESCOPE_HEADERS = {
    "accept": "application/json",
    "content-type": "application/json",
    "origin": "https://you.com",
    "referer": "https://you.com/",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "cross-site",
    "user-agent": _UA,
    "authorization": f"Bearer {DESCOPE_PROJECT_ID}",
}


class YouService(BaseService):
    name = "you"
    signup_url = "https://you.com/"
    api_key_prefix = "ydc-sk-"
    output_file = "you_accounts.txt"
    headless_config_key = "YOU_REGISTER_HEADLESS"

    # ------------------------------------------------------------------
    # 主入口 — 完全绕开 BaseService.register() 的浏览器流程
    # ------------------------------------------------------------------
    def register(self, email, password):
        sess = requests.Session()

        # Step 0: warm-up — 让 Cloudflare 设置 uuid_guest cookie
        self._warm_up(sess)

        # Step 1 & 2: 发 OTP 邮件，等验证码（signup 失败时自动切 signin）
        otp_code, is_new = self._request_otp_and_get_code(sess, email)
        if not otp_code:
            return None

        # Step 3: 验证 OTP，DS/DSR cookies 自动注入 sess
        if not self._verify_otp(sess, email, otp_code):
            return None

        # Step 4 & 5: 获取 action 参数，提交 Server Action 创建 key
        api_key = self._create_api_key(sess)
        if not api_key:
            print("[you] Failed to create API key")
            return None

        # Step 6: 验证并保存
        self._do_post_verify(api_key)
        self._save_result(email, password, api_key)
        return api_key

    # ------------------------------------------------------------------
    # 步骤实现
    # ------------------------------------------------------------------

    def _warm_up(self, sess):
        """访问 you.com/signin，让 Cloudflare 设置 uuid_guest cookie。"""
        try:
            sess.get("https://you.com/signin", headers=_NAV_HEADERS, timeout=15)
        except Exception as e:
            print(f"[you] Warm-up warning: {e}")

    def _request_otp_and_get_code(self, sess, email):
        """
        发送 OTP 并等待验证码，返回 (code, is_new_account)。
        自动尝试 signup → signin 降级。
        返回 (None, False) 表示失败。
        """
        from mail.factory import get_provider
        provider = get_provider()

        # 在发 OTP 前先记录已有邮件 ID，避免复用旧验证码
        existing_ids = provider.get_existing_message_ids(email)

        for endpoint, label, is_new in [
            (f"{DESCOPE_BASE}/v1/auth/otp/signup/email", "signup", True),
            (f"{DESCOPE_BASE}/v1/auth/otp/signin/email", "signin", False),
        ]:
            try:
                r = sess.post(
                    endpoint,
                    json={"loginId": email},
                    headers=_DESCOPE_HEADERS,
                    timeout=15,
                )
            except Exception as e:
                print(f"[you] OTP {label} request failed: {e}")
                return None, False

            if r.status_code == 200:
                masked = r.json().get("maskedEmail", "?")
                print(f"[you] OTP sent ({label}) to {masked}")

                code = provider.get_email_code(
                    email,
                    timeout=config.EMAIL_CODE_TIMEOUT,
                    service_hint="you",
                    skip_ids=existing_ids,
                )
                if not code:
                    print("[you] Failed to get OTP code from email")
                    return None, False
                return code, is_new

            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            error_code = body.get("errorCode", "") if isinstance(body, dict) else ""

            # E062503 = "User already exists" → 切换到 signin
            if error_code in ("E062503",) or "already" in str(body).lower():
                print("[you] Email already registered, switching to sign-in")
                continue

            print(f"[you] OTP {label} error {r.status_code}: {body}")
            return None, False

        return None, False

    def _verify_otp(self, sess, email, code):
        """
        POST auth.you.com/v1/auth/otp/verify/email
        成功后 DS/DSR cookies 通过 Set-Cookie 自动注入 sess.cookies。
        返回 True/False。
        """
        try:
            r = sess.post(
                f"{DESCOPE_BASE}/v1/auth/otp/verify/email",
                json={"loginId": email, "code": code},
                headers=_DESCOPE_HEADERS,
                timeout=15,
            )
        except Exception as e:
            print(f"[you] OTP verify request failed: {e}")
            return False

        if r.status_code != 200:
            print(f"[you] OTP verify failed {r.status_code}: {r.text[:200]}")
            return False

        # 确认 DSR cookie 存在（Descope session）
        dsr = sess.cookies.get("DSR", domain=".you.com")
        if not dsr:
            # 也尝试不带 domain 前缀
            dsr = next((c.value for c in sess.cookies if c.name == "DSR"), None)
        if not dsr:
            print("[you] OTP verify succeeded but DSR cookie not found")
            return False

        print("[you] OTP verified, session obtained")
        return True

    def _create_api_key(self, sess):
        """
        1. GET /platform/api-keys → 提取 Server Action 参数
        2. POST /platform/api-keys (multipart/form-data) → 解析 RSC 响应提取 key
        """
        # Step 4: 获取页面，提取 action 参数
        try:
            r_page = sess.get(
                "https://you.com/platform/api-keys",
                headers={**_NAV_HEADERS, "sec-fetch-site": "same-origin"},
                timeout=20,
            )
        except Exception as e:
            print(f"[you] Failed to fetch /platform/api-keys: {e}")
            return None

        if r_page.status_code != 200:
            print(f"[you] /platform/api-keys returned {r_page.status_code}")
            return None

        action_id, action_1_0, action_1_1, action_key = self._extract_action_params(r_page.text)
        print(f"[you] Server Action ID: {action_id[:16]}..., KEY: {action_key[:8]}...")

        # Step 5: 提交 Server Action
        key_name = f"auto-key-{int(time.time())}"
        try:
            r_create = sess.post(
                "https://you.com/platform/api-keys",
                files={
                    "_1_$ACTION_REF_1": (None, ""),
                    "_1_$ACTION_1:0": (None, action_1_0),
                    "_1_$ACTION_1:1": (None, action_1_1),
                    "_1_$ACTION_KEY": (None, action_key),
                    "_1_name": (None, key_name),
                    "0": (None, "[" + action_1_1 + ',"$K1"]'),
                },
                headers={
                    "accept": "text/x-component",
                    "next-action": action_id,
                    "origin": "https://you.com",
                    "referer": "https://you.com/platform/api-keys",
                    "user-agent": _UA,
                    "sec-fetch-site": "same-origin",
                    "sec-fetch-mode": "cors",
                },
                timeout=30,
            )
        except Exception as e:
            print(f"[you] Server Action POST failed: {e}")
            return None

        if r_create.status_code != 200:
            print(f"[you] Server Action returned {r_create.status_code}: {r_create.text[:200]}")
            return None

        # 从 RSC payload 提取 ydc-sk-... 格式的 key
        api_key = self._extract_key_from_rsc(r_create.text)
        if api_key:
            print(f"[you] API key created: {api_key[:20]}...")
            return api_key

        print(f"[you] Server Action succeeded but key not found in RSC response")
        return None

    @staticmethod
    def _extract_action_params(html: str):
        """从 /platform/api-keys 页面 HTML 提取 Server Action 参数。"""
        m0 = re.search(r'name="\$ACTION_1:0" value="([^"]+)"', html)
        m1 = re.search(r'name="\$ACTION_1:1" value="([^"]+)"', html)
        mk = re.search(r'name="\$ACTION_KEY" value="([^"]+)"', html)
        mid = re.search(r'"id"\s*:\s*"([0-9a-f]{40,})"', _html_mod.unescape(m0.group(1)) if m0 else "")

        action_id = mid.group(1) if mid else _SERVER_ACTION_ID
        action_1_0 = _html_mod.unescape(m0.group(1)) if m0 else f'{{"id":"{action_id}","bound":"$@1"}}'
        action_1_1 = _html_mod.unescape(m1.group(1)) if m1 else '[{"errorMap":{"onServer":"$undefined"},"values":"$undefined","errors":[]}]'
        action_key = mk.group(1) if mk else "k4cb809cd0c4e7e5070df726fd89de5fc"

        return action_id, action_1_0, action_1_1, action_key

    @staticmethod
    def _extract_key_from_rsc(rsc_text: str):
        """从 Next.js RSC (text/x-component) payload 提取 ydc-sk-... API key。"""
        keys = re.findall(r'ydc-sk-[a-zA-Z0-9_\-]{20,}', rsc_text)
        return keys[0] if keys else None

    # ------------------------------------------------------------------
    # 验证 & 保存（复用 BaseService 逻辑）
    # ------------------------------------------------------------------

    def _do_post_verify(self, api_key):
        if not api_key:
            return
        try:
            r = requests.get(
                "https://api.you.com/v1/search",
                params={"query": "test", "num_web_results": 1},
                headers={"X-API-Key": api_key, "Accept": "application/json"},
                timeout=getattr(config, "API_KEY_TIMEOUT", 30),
            )
            if r.status_code == 200:
                print("[you] API key verification passed")
            else:
                print(f"[you] API key verification failed: HTTP {r.status_code} {r.text[:120]}")
        except Exception as exc:
            print(f"[you] API key verification request failed: {exc}")

    def _save_result(self, email, password, api_key):
        with BaseService._SAVE_LOCK:
            with open(self.output_file, "a", encoding="utf-8") as f:
                f.write(f"{email},OTP_ONLY,{api_key}\n")

    # ------------------------------------------------------------------
    # BaseService abstract stubs（不再使用，但必须实现）
    # ------------------------------------------------------------------

    def _open_browser(self):
        raise NotImplementedError("YouService uses HTTP-only flow, no browser needed")

    def _navigate_to_signup(self, page):
        raise NotImplementedError

    def _fill_form(self, page, email, password):
        raise NotImplementedError

    def _submit_form(self, page):
        raise NotImplementedError

    def _verify_email(self, page, email):
        raise NotImplementedError

    def _extract_api_key(self, page):
        raise NotImplementedError
