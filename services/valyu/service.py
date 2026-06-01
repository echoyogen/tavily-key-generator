"""
ValyuService — HTTP 主路径 + 浏览器 Fallback

认证链路：
  1. GET  platform.valyu.ai/auth (warm-up，Cloudflare cookie 设置)
  2. GET  platform.valyu.ai/onboarding?email=...&provider=email (提取 next-action ID)
  3. POST platform.valyu.ai/onboarding?email=...&provider=email (Server Action，触发验证邮件)
       → 失败时降级: POST auth.valyu.ai/auth/v1/signup (Supabase 直连)
  4. 收取验证邮件中的 magic link (mail provider)
  5. GET  验证链接 (auth.valyu.ai/auth/v1/verify?token=...)，跟随重定向到 platform
  6. POST auth.valyu.ai/auth/v1/token?grant_type=password (密码登录，获取 access_token)
  7. GET  platform.valyu.ai/user/account/apikeys (提取或创建 API key)
   → 全链路失败时: patchright chromium 浏览器完成 11 步 onboarding
"""

import html as _html_mod
import random
import re
import time

import requests

import config
from services.base import BaseService

# 常量
SUPABASE_URL = "https://auth.valyu.ai"
SUPABASE_ANON_KEY = "sb_publishable_8AbrTfadTWE6iBwyjzK2TA_mJJbL0G6"
SUPABASE_PROJECT_REF = "znjddttyhmtuiyavinsb"  # from JWT iss field
SUPABASE_REST_URL = f"https://{SUPABASE_PROJECT_REF}.supabase.co/rest/v1"
PLATFORM_URL = "https://platform.valyu.ai"
_FALLBACK_ACTION_ID = "4049b0f006c0cc849cd70fb479842ca0d4c4bbade9"


def _extract_action_id_pattern1(html):
    """Extract action ID from $ACTION_1:0 wrapper containing nested JSON with "id" field."""
    m0 = re.search(r'name="\$ACTION_1:0" value="([^"]+)"', html)
    if not m0:
        return None
    mid = re.search(r'"id"\s*:\s*"([0-9a-f]{40,})"', _html_mod.unescape(m0.group(1)))
    return mid.group(1) if mid else None


def _extract_action_id_pattern2(html):
    """Extract action ID from direct "id" field in HTML (no outer $ACTION_1:0 wrapper)."""
    m = re.search(r'"id"\s*:\s*"([0-9a-f]{40,})"', html)
    return m.group(1) if m else None


_ACTION_ID_PATTERNS = (_extract_action_id_pattern1, _extract_action_id_pattern2)
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
_VALYU_KEY_RE = re.compile(r'val[a-z_]*[A-Za-z0-9_-]{20,}')

# 名字池和选项池（tuple，不可变全局状态）
_FIRST_NAMES = (
    "James", "Emma", "Liam", "Olivia", "Noah", "Ava", "William", "Sophia",
    "Benjamin", "Isabella", "Lucas", "Mia", "Henry", "Charlotte", "Alexander",
    "David", "Sarah", "Michael", "Emily", "Daniel", "Jessica", "Matthew",
    "Ashley", "Andrew", "Hannah", "Ryan", "Samantha", "Kevin", "Rachel",
)
_LAST_NAMES = (
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark",
)
_HEARD_FROM = (
    "linkedin", "twitter", "reddit", "search", "github", "friend", "other",
)
_ROLES = (
    "ai_developer", "non_ai_developer", "founder_cto", "vibe_coder", "researcher", "other",
)
_INDUSTRIES = (
    "technology", "finance", "healthcare", "education", "research", "media_entertainment", "other",
)
_TECHNOLOGIES = (
    "ai_sdk", "openai_sdk", "langchain", "mcp", "n8n", "non_technical",
)

# Header 字典
_NAV_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "user-agent": _UA,
}
_SUPABASE_HEADERS = {
    "accept": "application/json",
    "apikey": SUPABASE_ANON_KEY,
    "content-type": "application/json",
    "user-agent": _UA,
}
_PLATFORM_CORS_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "origin": PLATFORM_URL,
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": _UA,
}


class ValyuService(BaseService):
    name = "valyu"
    signup_url = "https://platform.valyu.ai/auth"
    api_key_prefix = "valyu-"
    output_file = "valyu_accounts.txt"
    headless_config_key = "VALYU_REGISTER_HEADLESS"

    # --- helpers ---
    @staticmethod
    def _log(step: str, msg: str) -> None:
        print(f"[valyu][{step}] {msg}")

    # ------------------------------------------------------------------
    # 主入口 (Task 6)
    # ------------------------------------------------------------------

    def register(self, email, password):
        """HTTP 主路径注册，全链路失败时 fallback 到 patchright 浏览器。"""
        sess = requests.Session()

        try:
            # Step 1: warm-up（让 Cloudflare 设置访客 cookie）
            self._warm_up(sess)

            # Step 2: 快照现有消息 ID（在发邮件前，避免复用旧消息）
            from mail.factory import get_provider
            provider = get_provider()
            existing_ids = provider.get_existing_message_ids(email)

            # Step 3: 提交 onboarding（主路径），失败时降级到 Supabase 直连
            ok = self._submit_onboarding(sess, email, password)
            if not ok:
                print("[valyu] Step 3 failed: onboarding rejected, trying Supabase fallback")
                ok = self._supabase_signup_fallback(sess, email, password)
            if not ok:
                print("[valyu] Step 3 failed: both onboarding and Supabase signup failed, falling back to browser")
                return self._browser_fallback(email, password)

            # Step 4: 等待验证邮件
            verify_link = provider.get_verification_link(email, timeout=config.EMAIL_CODE_TIMEOUT)
            if not verify_link:
                print("[valyu] Step 4 failed: verification email not received, falling back to browser")
                return self._browser_fallback(email, password)

            # Step 5: 访问验证链接并手动调用 Supabase verify，直接拿到 access_token
            verify_ok, access_token_from_verify = self._verify_via_link(sess, verify_link)
            if not verify_ok:
                print("[valyu] Step 5 failed: verify link did not land on platform, falling back to browser")
                return self._browser_fallback(email, password)

            # Step 6: 密码登录获取 access_token（若 step5 已返回 token 则跳过）
            if access_token_from_verify:
                access_token = access_token_from_verify
                self._log("step6", "skipped: access_token obtained from step5 verify")
            else:
                access_token = self._password_login(sess, email, password)
            if not access_token:
                print("[valyu] Step 6 failed: password login failed, falling back to browser")
                return self._browser_fallback(email, password)

            # Step 7: 获取 API key
            api_key = self._fetch_api_key_http(sess, access_token)
            if not api_key:
                print("[valyu] Step 7 failed: could not obtain API key via HTTP, falling back to browser")
                return self._browser_fallback(email, password, access_token=access_token)

            # Step 8: 验证并保存
            self._do_post_verify(api_key)
            self._save_result(email, password, api_key)
            return api_key

        except Exception as e:
            print(f"[valyu] HTTP flow error: {e}, falling back to browser")
            return self._browser_fallback(email, password)

    # ------------------------------------------------------------------
    # HTTP 初始化组 (Task 2)
    # ------------------------------------------------------------------

    def _warm_up(self, sess):
        """访问 platform.valyu.ai/auth，让 Cloudflare 设置访客 cookie。"""
        try:
            r = sess.get(f"{PLATFORM_URL}/auth", headers=_NAV_HEADERS, timeout=15)
            self._log("step1", f"status={r.status_code}, cookies={list(sess.cookies.keys())}")
        except Exception as e:
            print(f"[valyu] Warm-up warning: {e}")

    def _get_onboarding_page_html(self, sess, email):
        """GET onboarding 页面 HTML，动态提取 next-action ID，失败时使用 fallback。"""
        headers = {
            **_NAV_HEADERS,
            "sec-fetch-site": "same-origin",
            "referer": f"{PLATFORM_URL}/auth",
        }
        html = ""
        try:
            r = sess.get(
                f"{PLATFORM_URL}/onboarding?email={email}&provider=email",
                headers=headers,
                timeout=20,
            )
            html = r.text
        except Exception as e:
            print(f"[valyu] Failed to fetch onboarding page: {e}")

        # 从 HTML 动态提取 next-action hash（多 pattern 按序尝试）
        action_id = None
        for _pattern_fn in _ACTION_ID_PATTERNS:
            action_id = _pattern_fn(html)
            if action_id:
                break
        if not action_id:
            action_id = _FALLBACK_ACTION_ID
            self._log("step2", f"WARNING: using fallback next-action ID, html_snippet={html[:300]!r}")

        return html, action_id

    def _submit_onboarding(self, sess, email, password):
        """提交 onboarding Server Action，触发验证邮件发送，返回是否成功。"""
        _, action_id = self._get_onboarding_page_html(sess, email)

        first_name = random.choice(_FIRST_NAMES)
        last_name = random.choice(_LAST_NAMES)
        username = re.sub(r"[^a-zA-Z0-9]", "", email.split("@")[0])

        payload = [{
            "userId": "",
            "email": email,
            "firstName": first_name,
            "lastName": last_name,
            "userName": username,
            "userType": "buyer",
            "organisation": None,
            "provider": "email",
            "avatarUrl": "",
            "platformMode": "developer",
            "heardFrom": random.choice(_HEARD_FROM),
            "role": random.choice(_ROLES),
            "industry": [random.choice(_INDUSTRIES)],
            "customHeardFrom": "",
            "customRole": "",
            "customIndustry": "",
            "technologyPreferences": [random.choice(_TECHNOLOGIES)],
            "redirect": "$undefined",
            "referrer": "$undefined",
            "referralCode": "$undefined",
            "promoCode": "$undefined",
            "inviteToken": "$undefined",
            "password": password,
            "usePassword": True,
            "captchaToken": "$undefined",
        }]

        import json as _json
        headers = {
            "Content-Type": "text/plain;charset=UTF-8",
            "Accept": "text/x-component",
            "next-action": action_id,
            "Referer": f"{PLATFORM_URL}/onboarding?email={email}&provider=email",
            "Origin": PLATFORM_URL,
            "sec-fetch-site": "same-origin",
            "sec-fetch-mode": "cors",
            "User-Agent": _UA,
        }

        try:
            r = sess.post(
                f"{PLATFORM_URL}/onboarding?email={email}&provider=email",
                data=_json.dumps(payload),
                headers=headers,
                timeout=30,
            )
            self._log("step3", f"status={r.status_code}, resp={r.text[:300]!r}")
        except Exception as e:
            print(f"[valyu] Onboarding POST failed: {e}")
            return False

        success = r.status_code in (200, 302, 303) and "error" not in r.text.lower()
        if not success:
            print(f"[valyu] Onboarding failed ({r.status_code}): {r.text[:300]}")
        return success

    def _supabase_signup_fallback(self, sess, email, password):
        """直接调用 Supabase Auth API 注册，作为 onboarding Server Action 的降级方案。"""
        try:
            r = sess.post(
                f"{SUPABASE_URL}/auth/v1/signup",
                json={"email": email, "password": password},
                headers=_SUPABASE_HEADERS,
                timeout=20,
            )
            self._log("step3_supa", f"status={r.status_code}, resp={r.text[:300]!r}")
        except Exception as e:
            print(f"[valyu] Supabase signup request failed: {e}")
            return False

        if r.status_code == 200:
            data = r.json()
            if "id" in data:
                return True
            print(f"[valyu] Supabase signup unexpected response: {r.text[:200]}")
            return False

        if r.status_code == 422:
            body = r.text.lower()
            if "user already registered" in body:
                print("[valyu] WARNING: user already registered via Supabase, continuing")
                return True

        print(f"[valyu] Supabase signup failed ({r.status_code}): {r.text[:200]}")
        return False

    # ------------------------------------------------------------------
    # 验证组 (Task 3)
    # ------------------------------------------------------------------

    def _wait_and_verify_email(self, email):
        from mail.factory import get_provider
        provider = get_provider()

        print(f"[valyu] Waiting for verification email (up to {config.EMAIL_CODE_TIMEOUT}s)...")
        link = provider.get_verification_link(email, timeout=config.EMAIL_CODE_TIMEOUT)
        if not link:
            print(f"[valyu] Error: Verification email not received for {email}")
            return None
        return link

    def _verify_via_link(self, sess, link):
        """Follow verify link, log redirect chain, then manually call Supabase verify API.

        /auth/confirm?token_hash=... is a Next.js frontend page that requires JS to POST
        to Supabase. We extract token_hash and call the API directly instead.
        Returns (bool, access_token_or_None).
        """
        import urllib.parse as _urlparse

        try:
            r = sess.get(link, headers=_NAV_HEADERS, allow_redirects=True, timeout=60)
        except Exception as e:
            print(f"[valyu] Verify link request failed: {e}")
            return (False, None)

        # Log complete redirect chain
        chain = r.history + [r]
        for i, resp in enumerate(chain):
            url_safe = (resp.url or "")[:80]
            loc_safe = (resp.headers.get("Location") or "")[:80]
            self._log("step5", f"redirect[{i}]: {resp.status_code} {url_safe} -> {loc_safe}")

        final_url = r.url if hasattr(r, "url") else ""
        self._log("step5", f"final_url={final_url[:120]!r}")

        # Detect error query params
        qs = _urlparse.parse_qs(_urlparse.urlparse(final_url).query)
        if "error" in qs or "error_code" in qs:
            err = qs.get("error", qs.get("error_code", []))[0]
            self._log("step5", f"FAIL: error param detected: {err!r}")
            return (False, None)

        if r.status_code not in range(200, 400) or "platform.valyu.ai" not in final_url.lower():
            print(f"[valyu] WARNING: verify link may have failed (status={r.status_code}, url={r.url})")
            return (False, None)

        # /auth/confirm?token_hash=... is a JS-driven page; requests cannot execute JS.
        # Extract token_hash and call Supabase verify endpoint directly.
        token_hash = qs.get("token_hash", [None])[0]
        verify_type = qs.get("type", ["signup"])[0]

        if not token_hash:
            self._log("step5", "WARNING: no token_hash in final_url, assuming pre-confirmed")
            return (True, None)

        try:
            vr = sess.post(
                f"{SUPABASE_URL}/auth/v1/verify",
                json={"token_hash": token_hash, "type": verify_type},
                headers=_SUPABASE_HEADERS,
                timeout=20,
            )
            self._log("step5_verify", f"status={vr.status_code}, resp={vr.text[:200]!r}")
        except Exception as e:
            print(f"[valyu] Supabase verify request failed: {e}")
            return (False, None)

        if vr.status_code == 200:
            access_token = vr.json().get("access_token")
            return (True, access_token)

        self._log("step5_verify", f"FAIL: status={vr.status_code}")
        return (False, None)

    def _password_login(self, sess, email, password):
        # error_code field: verified from live response {"code":400,"error_code":"email_not_confirmed","msg":"Email not confirmed"}
        max_attempts = 4
        for attempt in range(max_attempts):
            if attempt > 0:
                wait = 3 * attempt  # 3s, 6s, 9s
                self._log("step6", f"retry #{attempt} in {wait}s (email_not_confirmed)")
                time.sleep(wait)
            try:
                r = sess.post(
                    f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
                    json={"email": email, "password": password},
                    headers=_SUPABASE_HEADERS,
                    timeout=20,
                )
                self._log("step6", f"attempt={attempt}, status={r.status_code}, resp={r.text[:200]!r}")
            except Exception as e:
                print(f"[valyu] Password login request failed: {e}")
                return None

            if r.status_code == 200:
                data = r.json()
                token = data.get("access_token")
                if token:
                    return token
                print(f"[valyu] Login response missing access_token: {r.text[:200]}")
                return None

            # Retry only on email_not_confirmed
            try:
                error_code = r.json().get("error_code")
            except Exception:
                error_code = None

            if r.status_code == 400 and error_code == "email_not_confirmed":
                continue

            # Non-retryable error
            print(f"[valyu] Password login failed ({r.status_code}): {r.text[:200]}")
            return None

        self._log("step6", f"FAIL: email still not confirmed after {max_attempts} attempts")
        return None

    # ------------------------------------------------------------------
    # Key 获取组 (Task 4)
    # ------------------------------------------------------------------

    def _extract_valyu_key(self, text):
        matches = _VALYU_KEY_RE.findall(text)
        return matches[0] if matches else None

    def _fetch_existing_key_rest(self, access_token):
        """Try to read an existing API key from Supabase PostgREST (SELECT is allowed by RLS).

        Valyu stores api_keys in a Supabase table with RLS: users can SELECT their own rows.
        INSERT/UPDATE is blocked, so this only works if a key already exists.
        Returns the key string or None.
        """
        try:
            import requests as _req
            r = _req.get(
                f"{SUPABASE_REST_URL}/api_keys",
                params={"select": "*", "limit": "1"},
                headers={
                    "apikey": SUPABASE_ANON_KEY,
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                    "user-agent": _UA,
                },
                timeout=15,
            )
            self._log("step7_rest", f"status={r.status_code}, resp={r.text[:200]!r}")
            if r.status_code == 200:
                rows = r.json()
                if rows:
                    # Look for a key value in common column names
                    row = rows[0]
                    for col in ("api_key", "key", "value", "token", "secret"):
                        val = row.get(col)
                        if val and self._extract_valyu_key(str(val)):
                            return self._extract_valyu_key(str(val))
                    # Try all string values in the row
                    for val in row.values():
                        if isinstance(val, str):
                            k = self._extract_valyu_key(val)
                            if k:
                                return k
        except Exception as e:
            self._log("step7_rest", f"ERROR: {e}")
        return None

    def _fetch_api_key_http(self, sess, access_token):
        # First try reading an existing key via Supabase REST API (fast, no Server Action needed)
        existing = self._fetch_existing_key_rest(access_token)
        if existing:
            self._log("step7", "obtained existing key via Supabase REST")
            return existing

        # Fall back to Server Action (requires a valid action ID from SSR, usually fails without browser)
        headers = {
            **_NAV_HEADERS,
            "Authorization": f"Bearer {access_token}",
            "sec-fetch-site": "same-origin",
        }

        try:
            r = sess.get(
                f"{PLATFORM_URL}/user/account/apikeys",
                headers=headers,
                timeout=20,
            )
            self._log("step7_get", f"status={r.status_code}, html_len={len(r.text)}")
        except Exception as e:
            print(f"[valyu] Failed to fetch API keys page: {e}")
            return None

        api_key = self._extract_valyu_key(r.text)
        if api_key:
            return api_key

        action_id = None
        for _pattern_fn in _ACTION_ID_PATTERNS:
            action_id = _pattern_fn(r.text)
            if action_id:
                break
        if not action_id:
            action_id = _FALLBACK_ACTION_ID
            self._log("step7_create", f"WARNING: using fallback next-action ID, html_snippet={r.text[:300]!r}")

        key_name = f"auto-key-{int(time.time())}"
        try:
            create_resp = sess.post(
                f"{PLATFORM_URL}/user/account/apikeys",
                files={
                    "_1_name": (None, key_name),
                },
                headers={
                    "accept": "text/x-component",
                    "next-action": action_id,
                    "origin": PLATFORM_URL,
                    "referer": f"{PLATFORM_URL}/user/account/apikeys",
                    "authorization": f"Bearer {access_token}",
                    "user-agent": _UA,
                    "sec-fetch-site": "same-origin",
                    "sec-fetch-mode": "cors",
                },
                timeout=30,
            )
            self._log("step7_create", f"status={create_resp.status_code}, resp={create_resp.text[:200]!r}")
        except Exception as e:
            print(f"[valyu] Server Action POST failed: {e}")
            return None

        if create_resp.status_code != 200:
            print(f"[valyu] Server Action returned {create_resp.status_code}: {create_resp.text[:200]}")
            return None

        api_key = self._extract_valyu_key(create_resp.text)
        if not api_key:
            print("[valyu] Could not extract API key from HTTP response")
        return api_key

    def _do_post_verify(self, api_key):
        if not api_key:
            return
        try:
            r = requests.post(
                "https://api.valyu.ai/v1/search",
                json={"query": "test", "max_num_results": 1},
                headers={"x-api-key": api_key, "Content-Type": "application/json"},
                timeout=getattr(config, "API_KEY_TIMEOUT", 30),
            )
            if r.status_code == 200:
                print("[valyu] API key verification passed")
            else:
                print(f"[valyu] WARNING: API key verification failed: HTTP {r.status_code} {r.text[:120]}")
        except Exception as exc:
            print(f"[valyu] WARNING: API key verification request failed: {exc}")

    def _save_result(self, email, password, api_key):
        with BaseService._SAVE_LOCK:
            with open(self.output_file, "a", encoding="utf-8") as f:
                f.write(f"{email},{password},{api_key}\n")

    # ------------------------------------------------------------------
    # 浏览器 fallback (Task 5)
    # ------------------------------------------------------------------

    def _browser_fallback(self, email, password, access_token=None):
        """Patchright browser completes onboarding and extracts API key.

        If access_token is provided (HTTP flow already registered+verified the account),
        inject the session cookie directly and skip the registration flow entirely —
        just complete onboarding and navigate to the API keys page.
        Otherwise fall back to full registration flow.
        """
        import json as _json
        import urllib.parse as _urlparse

        try:
            first_name = random.choice(_FIRST_NAMES)
            last_name = random.choice(_LAST_NAMES)

            browser_cm = BaseService._open_browser(self)
            browser = browser_cm.__enter__()
            try:
                page = browser.new_page()

                if access_token:
                    # Fast path: inject Supabase session cookie and go straight to the platform
                    self._log("browser", "access_token available — injecting session cookie, skipping signup")
                    session_data = _json.dumps({
                        "access_token": access_token,
                        "token_type": "bearer",
                        "expires_in": 3600,
                        "refresh_token": "",
                    })
                    # @supabase/ssr splits large values into .0/.1 chunks; inject both formats
                    cookie_name = f"sb-{SUPABASE_PROJECT_REF}-auth-token"
                    page.context.add_cookies([{
                        "name": cookie_name,
                        "value": session_data,
                        "domain": "platform.valyu.ai",
                        "path": "/",
                    }])
                    # Also set the URL-encoded variant some Next.js Supabase helpers use
                    page.context.add_cookies([{
                        "name": cookie_name,
                        "value": _urlparse.quote(session_data),
                        "domain": "platform.valyu.ai",
                        "path": "/",
                    }])

                    page.goto(f"{PLATFORM_URL}/user/account/apikeys",
                              wait_until="domcontentloaded", timeout=45000)
                    time.sleep(4)

                    # If redirected to onboarding, complete it
                    if "onboarding" in page.url:
                        self._log("browser", "redirected to onboarding — completing it")
                        self._complete_onboarding(page, first_name, last_name, password)
                        page.goto(f"{PLATFORM_URL}/user/account/apikeys",
                                  wait_until="domcontentloaded", timeout=30000)
                        time.sleep(3)
                    # If redirected to auth, session cookie wasn't accepted; fall through to full signup
                    elif "auth" in page.url and "apikeys" not in page.url:
                        self._log("browser", "cookie injection failed (redirected to /auth) — falling back to full signup")
                        access_token = None  # trigger full flow below

                if not access_token:
                    # Full registration flow
                    page.goto(f"{PLATFORM_URL}/auth", wait_until="domcontentloaded", timeout=45000)
                    time.sleep(2)

                    email_selectors = [
                        'input[placeholder="name@example.com"]',
                        'input[type="email"]',
                        'input[name="email"]',
                        'input[autocomplete="email"]',
                    ]
                    filled = False
                    for sel in email_selectors:
                        try:
                            page.wait_for_selector(sel, timeout=8000, state="visible")
                            page.fill(sel, email)
                            filled = True
                            self._log("browser", f"email filled via selector: {sel}")
                            break
                        except Exception:
                            continue
                    if not filled:
                        self._log("browser", "FAIL: no email input found with any selector")
                        return None
                    page.click('button:has-text("Continue with Email")')
                    page.wait_for_url("**/onboarding**", timeout=15000)

                    self._complete_onboarding(page, first_name, last_name, password)

                    # wait for verification email
                    verify_link = self._wait_and_verify_email(email)
                    if verify_link:
                        page.goto(verify_link, wait_until="domcontentloaded", timeout=60000)
                        time.sleep(5)

                    page.goto(f"{PLATFORM_URL}/user/account/apikeys",
                              wait_until="domcontentloaded", timeout=30000)
                    time.sleep(3)

                # extract key from page
                html = page.content()
                api_key = self._extract_valyu_key(html)

                if not api_key:
                    # try extracting from visible elements
                    for selector in ['input[type="text"]', 'code', 'input[readonly]']:
                        elements = page.query_selector_all(selector)
                        for element in elements:
                            try:
                                text = element.inner_text() or element.get_attribute('value') or ''
                            except Exception:
                                text = ''
                            api_key = self._extract_valyu_key(text)
                            if api_key:
                                break
                        if api_key:
                            break

                self._do_post_verify(api_key)
                self._save_result(email, password, api_key)
                return api_key

            finally:
                try:
                    browser_cm.__exit__(None, None, None)
                except Exception as teardown_exc:
                    print(f"[valyu] Browser cleanup warning: {teardown_exc}")

        except Exception as e:
            print(f"[valyu] Browser fallback failed: {e}")
            return None

    def _complete_onboarding(self, page, first_name, last_name, password):
        """Fill the multi-step onboarding form (steps 3-11 of the browser flow)."""
        # fill name fields
        page.fill('input[name="firstName"]', first_name)
        page.fill('input[name="lastName"]', last_name)

        # enable password mode if toggle exists
        try:
            page.locator('button[role="switch"]:near(:text("Use password"))').click(timeout=3000)
            page.wait_for_selector('input[type="password"]', timeout=5000)
            page.locator('input[type="password"]').nth(0).fill(password)
            page.locator('input[type="password"]').nth(1).fill(password)
        except Exception:
            pass

        page.click('button:has-text("Continue"):not([disabled])')
        time.sleep(1)

        page.click('button:has-text("Developer")')
        page.click('button:has-text("Continue"):not([disabled])')
        time.sleep(0.5)

        source = random.choice(["LinkedIn", "Twitter/X", "Reddit", "Search Engine", "GitHub"])
        page.locator(f'button:has-text("{source}")').click()
        page.click('button:has-text("Continue"):not([disabled])')
        time.sleep(0.5)

        role = random.choice(["AI Developer", "Founder/CTO", "Vibe Coder", "Researcher"])
        page.locator(f'button:has-text("{role}")').click()
        page.click('button:has-text("Continue"):not([disabled])')
        time.sleep(0.5)

        page.click('button:has-text("Technology")')
        page.click('button:has-text("Continue"):not([disabled])')
        time.sleep(0.5)

        tech = random.choice(["MCP", "OpenAI SDK", "LangChain", "AI SDK"])
        page.locator(f'button:has-text("{tech}")').click()
        page.click('button:has-text("Continue"):not([disabled])')
        time.sleep(1)

        scroll_btn = page.locator('button:has-text("Scroll to bottom")')
        if scroll_btn.is_visible():
            scroll_btn.click()
            time.sleep(0.5)

        try:
            page.locator('input[type="checkbox"], [role="checkbox"]').click()
        except Exception:
            pass

        page.click('button:has-text("Finish setup")')
        time.sleep(3)

    # ------------------------------------------------------------------
    # Abstract method stubs (Task 5)
    # ------------------------------------------------------------------

    def _open_browser(self):
        raise NotImplementedError("ValyuService uses HTTP-primary flow; _browser_fallback() handles browser path directly")

    def _navigate_to_signup(self, page):
        raise NotImplementedError("ValyuService uses HTTP-primary flow; _browser_fallback() handles browser path directly")

    def _fill_form(self, page, email, password):
        raise NotImplementedError("ValyuService uses HTTP-primary flow; _browser_fallback() handles browser path directly")

    def _submit_form(self, page):
        raise NotImplementedError("ValyuService uses HTTP-primary flow; _browser_fallback() handles browser path directly")

    def _verify_email(self, page, email):
        raise NotImplementedError("ValyuService uses HTTP-primary flow; _browser_fallback() handles browser path directly")

    def _extract_api_key(self, page):
        raise NotImplementedError("ValyuService uses HTTP-primary flow; _browser_fallback() handles browser path directly")
