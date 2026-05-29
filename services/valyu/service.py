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
  → 全链路失败时: Camoufox 浏览器完成 11 步 onboarding
"""

import html as _html_mod
import random
import re
import string
import time

import requests

import config
from services.base import BaseService

# 常量
SUPABASE_URL = "https://auth.valyu.ai"
SUPABASE_ANON_KEY = "sb_publishable_8AbrTfadTWE6iBwyjzK2TA_mJJbL0G6"
PLATFORM_URL = "https://platform.valyu.ai"
_FALLBACK_ACTION_ID = "4049b0f006c0cc849cd70fb479842ca0d4c4bbade9"
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

    # ------------------------------------------------------------------
    # 主入口 (Task 6)
    # ------------------------------------------------------------------

    def register(self, email, password):
        """HTTP 主路径注册，全链路失败时 fallback 到 Camoufox 浏览器。"""
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

            # Step 5: 访问验证链接（失败只 warn，继续，cookies 可能已设置）
            self._verify_via_link(sess, verify_link)
            time.sleep(2)

            # Step 6: 密码登录获取 access_token
            access_token = self._password_login(sess, email, password)
            if not access_token:
                print("[valyu] Step 6 failed: password login failed, falling back to browser")
                return self._browser_fallback(email, password)

            # Step 7: 获取 API key
            api_key = self._fetch_api_key_http(sess, access_token)
            if not api_key:
                print("[valyu] Step 7 failed: could not obtain API key via HTTP, falling back to browser")
                return self._browser_fallback(email, password)

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
            sess.get(f"{PLATFORM_URL}/auth", headers=_NAV_HEADERS, timeout=15)
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

        # 从 HTML 动态提取 next-action hash
        m0 = re.search(r'name="\$ACTION_1:0" value="([^"]+)"', html)
        mid = re.search(
            r'"id"\s*:\s*"([0-9a-f]{40,})"',
            _html_mod.unescape(m0.group(1)) if m0 else "",
        )

        if mid:
            action_id = mid.group(1)
        else:
            action_id = _FALLBACK_ACTION_ID
            print("[valyu] WARNING: using fallback next-action ID")

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
        try:
            r = sess.get(link, headers=_NAV_HEADERS, allow_redirects=True, timeout=60)
        except Exception as e:
            print(f"[valyu] Verify link request failed: {e}")
            return False

        time.sleep(2)

        final_url = r.url.lower() if hasattr(r, "url") else ""
        if r.status_code not in range(200, 400) or "platform.valyu.ai" not in final_url:
            print(f"[valyu] WARNING: verify link may have failed (status={r.status_code}, url={r.url})")
            return False

        return True

    def _password_login(self, sess, email, password):
        try:
            r = sess.post(
                f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
                json={"email": email, "password": password},
                headers=_SUPABASE_HEADERS,
                timeout=20,
            )
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

        print(f"[valyu] Password login failed ({r.status_code}): {r.text[:200]}")
        return None

    # ------------------------------------------------------------------
    # Key 获取组 (Task 4)
    # ------------------------------------------------------------------

    def _extract_valyu_key(self, text):
        matches = _VALYU_KEY_RE.findall(text)
        return matches[0] if matches else None

    def _fetch_api_key_http(self, sess, access_token):
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
        except Exception as e:
            print(f"[valyu] Failed to fetch API keys page: {e}")
            return None

        api_key = self._extract_valyu_key(r.text)
        if api_key:
            return api_key

        m0 = re.search(r'name="\$ACTION_1:0" value="([^"]+)"', r.text)
        mid = re.search(
            r'"id"\s*:\s*"([0-9a-f]{40,})"',
            _html_mod.unescape(m0.group(1)) if m0 else "",
        )
        action_id = mid.group(1) if mid else _FALLBACK_ACTION_ID

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

    def _browser_fallback(self, email, password):
        """Camoufox browser completes full 11-step onboarding (final fallback when HTTP chain fails)."""
        try:
            first_name = random.choice(_FIRST_NAMES)
            last_name = random.choice(_LAST_NAMES)

            browser_cm = BaseService._open_browser(self)
            browser = browser_cm.__enter__()
            try:
                page = browser.new_page()

                # Step 1: open signup page
                page.goto(f"{PLATFORM_URL}/auth", wait_until="domcontentloaded", timeout=30000)
                time.sleep(2)

                # Step 2: enter email and proceed to onboarding
                page.fill('input[placeholder="name@example.com"]', email)
                page.click('button:has-text("Continue with Email")')
                page.wait_for_url("**/onboarding**", timeout=15000)

                # Step 3: fill firstName and lastName
                page.fill('input[name="firstName"]', first_name)
                page.fill('input[name="lastName"]', last_name)

                # Step 4: enable password mode
                page.locator('button[role="switch"]:near(:text("Use password"))').click()
                page.wait_for_selector('input[type="password"]', timeout=5000)

                # Step 5: fill password fields
                page.locator('input[type="password"]').nth(0).fill(password)
                page.locator('input[type="password"]').nth(1).fill(password)

                # Step 6: click Continue
                page.click('button:has-text("Continue"):not([disabled])')
                time.sleep(1)

                # Step 7: select platform Developer
                page.click('button:has-text("Developer")')
                page.click('button:has-text("Continue"):not([disabled])')
                time.sleep(0.5)

                # Step 8: select source (random)
                source = random.choice(["LinkedIn", "Twitter/X", "Reddit", "Search Engine", "GitHub"])
                page.locator(f'button:has-text("{source}")').click()
                page.click('button:has-text("Continue"):not([disabled])')
                time.sleep(0.5)

                # Step 9: select role (random)
                role = random.choice(["AI Developer", "Founder/CTO", "Vibe Coder", "Researcher"])
                page.locator(f'button:has-text("{role}")').click()
                page.click('button:has-text("Continue"):not([disabled])')
                time.sleep(0.5)

                # Step 10: select industry Technology
                page.click('button:has-text("Technology")')
                page.click('button:has-text("Continue"):not([disabled])')
                time.sleep(0.5)

                # Step 11: select technology (random) + finish setup
                tech = random.choice(["MCP", "OpenAI SDK", "LangChain", "AI SDK"])
                page.locator(f'button:has-text("{tech}")').click()
                page.click('button:has-text("Continue"):not([disabled])')
                time.sleep(1)

                # handle scroll-to-bottom and checkbox
                scroll_btn = page.locator('button:has-text("Scroll to bottom")')
                if scroll_btn.is_visible():
                    scroll_btn.click()
                    time.sleep(0.5)

                checkbox = page.locator('input[type="checkbox"], [role="checkbox"]')
                try:
                    checkbox.click()
                except Exception:
                    pass

                page.click('button:has-text("Finish setup")')
                time.sleep(3)

                # wait for verification email
                verify_link = self._wait_and_verify_email(email)
                if verify_link:
                    page.goto(verify_link, wait_until="domcontentloaded", timeout=60000)
                    time.sleep(5)

                # navigate to API keys page
                page.goto(f"{PLATFORM_URL}/user/account/apikeys", wait_until="domcontentloaded", timeout=30000)
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
