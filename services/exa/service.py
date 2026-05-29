import json
import re
import time

import requests

from services.base import BaseService
from services.common.browser import click_first, extract_api_key_by_pattern, fill_first_input
from services.common.api_verifier import verify_api_key

_EXA_AUTH_URL = "https://auth.exa.ai/?callbackUrl=https%3A%2F%2Fdashboard.exa.ai%2F"
_EXA_HOME_URL = "https://dashboard.exa.ai/home"


def _fetch_api_key_via_dashboard_api(page):
    try:
        payload = page.evaluate(
            """
            async () => {
                const response = await fetch('/api/get-api-keys', {
                    method: 'GET',
                    credentials: 'include',
                    headers: {
                        'accept': 'application/json',
                    },
                });
                return {
                    status: response.status,
                    body: await response.text(),
                };
            }
            """
        )
    except Exception:
        return None

    if int(payload.get("status") or 0) != 200:
        return None

    try:
        data = json.loads(payload.get("body") or "{}")
    except Exception:
        return None

    for item in data.get("apiKeys", []):
        candidate = (item.get("id") or "").strip()
        if re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", candidate, re.I):
            return candidate
    return None


def _ensure_dashboard_ready(page):
    if "dashboard.exa.ai" not in page.url.lower():
        page.wait_for_url("**/dashboard.exa.ai/**", timeout=30000, wait_until="domcontentloaded")

    if "/onboarding" in page.url.lower():
        click_first(page, ['button:text-is("Skip")'])
        time.sleep(1)
        click_first(
            page,
            [
                'button:text-is("Yes, I don\'t want the $10 in credits anyway!")',
                'button:text-is("Yes")',
            ],
        )
        page.wait_for_url("**/dashboard.exa.ai/**", timeout=30000, wait_until="domcontentloaded")
        time.sleep(2)

    if "/home" not in page.url.lower():
        page.goto(_EXA_HOME_URL, wait_until="domcontentloaded", timeout=30000)
        time.sleep(2)


class ExaService(BaseService):
    name = "exa"
    signup_url = "https://exa.ai/"
    api_key_prefix = "exa-"
    output_file = "exa_accounts.txt"
    headless_config_key = "EXA_REGISTER_HEADLESS"

    def register(self, email, password):
        import config
        from mail.factory import get_provider

        sess = requests.Session()
        try:
            # Step 0: snapshot existing message IDs before triggering email
            provider = get_provider()
            existing_ids = provider.get_existing_message_ids(email)

            # Step 1: get CSRF token
            csrf_resp = sess.get(
                "https://auth.exa.ai/api/auth/csrf",
                headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
                timeout=15,
            )
            csrf_token = csrf_resp.json()["csrfToken"]

            # Step 2: trigger magic link email
            sess.post(
                "https://auth.exa.ai/api/auth/signin/email",
                data={"email": email, "csrfToken": csrf_token,
                      "callbackUrl": "https://dashboard.exa.ai/"},
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Referer": "https://auth.exa.ai/",
                    "User-Agent": "Mozilla/5.0",
                },
                timeout=15,
            )

            # Step 3: wait for magic link
            verify_link = provider.get_verification_link(email, timeout=config.EMAIL_CODE_TIMEOUT)
            if not verify_link:
                raise RuntimeError("No verification email received")

            # Step 4: follow magic link (sets session cookies)
            sess.get(verify_link, allow_redirects=True,
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=60)

            # Step 5: fetch API key
            key_resp = sess.get(
                "https://dashboard.exa.ai/api/get-api-keys",
                headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
                timeout=15,
            )
            data = key_resp.json()
            api_key = None
            for item in data.get("apiKeys", []):
                candidate = (item.get("id") or "").strip()
                if re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", candidate, re.I):
                    api_key = candidate
                    break
            if not api_key:
                raise RuntimeError(f"HTTP path: key extraction failed from response: {data}")

            self._do_post_verify(api_key)
            self._save_result(email, password, api_key)
            return api_key
        except Exception as e:
            print(f"[exa] HTTP flow error: {e}, falling back to browser")
            return self._browser_fallback(email, password)

    def _browser_fallback(self, email, password):
        try:
            browser_cm = BaseService._open_browser(self)
            browser = browser_cm.__enter__()
            try:
                page = browser.new_page()
                self._navigate_to_signup(page)
                email_selector = fill_first_input(
                    page,
                    ['input[type="email"]', 'input[placeholder="Email"]', 'input[aria-label="Email"]'],
                    email,
                )
                if not email_selector:
                    print("Exa: email input not found")
                if not click_first(page, ['button:text-is("Continue")']):
                    print("Exa: Continue button not found")
                page.wait_for_selector(
                    'input[placeholder*="verification" i], input[aria-label*="verification" i]',
                    timeout=30000,
                )
                print("Exa: reached OTP page")

                import mail.factory as mail_factory
                provider = mail_factory.get_provider()
                code = provider.get_email_code(email, service_hint="exa")
                if not code:
                    print("Exa: OTP code not received")
                else:
                    code_selector = fill_first_input(
                        page,
                        ['input[placeholder*="verification" i]', 'input[aria-label*="verification" i]'],
                        code,
                    )
                    if not code_selector:
                        print("Exa: OTP input not found")
                    else:
                        if not click_first(page, ['button:text-is("VERIFY CODE")', 'button:text-is("Verify Code")', 'button:text-is("Verify")']):
                            page.press(code_selector, "Enter")

                        page.wait_for_url("**/dashboard.exa.ai/**", timeout=30000, wait_until="domcontentloaded")
                        print("Exa: login successful")

                import config as _config
                timeout = getattr(_config, "API_KEY_TIMEOUT", 20)
                start_time = time.time()
                api_key = None
                while time.time() - start_time < timeout:
                    _ensure_dashboard_ready(page)
                    api_key = _fetch_api_key_via_dashboard_api(page)
                    if api_key:
                        break
                    click_first(page, ['button:text-is("Show")'])
                    time.sleep(1)
                    api_key = extract_api_key_by_pattern(page, r"exa-[a-zA-Z0-9_-]+")
                    if api_key:
                        break
                    time.sleep(1)
                self._do_post_verify(api_key)
                self._save_result(email, password, api_key)
                return api_key
            finally:
                try:
                    browser_cm.__exit__(None, None, None)
                except Exception as e:
                    print(f"[exa] Browser cleanup: {e}")
        except Exception as e:
            print(f"[exa] Browser fallback failed: {e}")
            return None

    def _navigate_to_signup(self, page):
        page.goto(_EXA_AUTH_URL, wait_until="domcontentloaded", timeout=30000)
        time.sleep(2)

    def _fill_form(self, page, email, password):
        raise NotImplementedError("_fill_form is superseded by register() and _browser_fallback()")

    def _submit_form(self, page):
        raise NotImplementedError("_submit_form is superseded by register() and _browser_fallback()")

    def _verify_email(self, page, email):
        raise NotImplementedError("_verify_email is superseded by register() and _browser_fallback()")

    def _extract_api_key(self, page):
        raise NotImplementedError("_extract_api_key is superseded by register() and _browser_fallback()")

    def _do_post_verify(self, api_key):
        if not api_key:
            return
        verify_api_key(
            api_key,
            endpoint="https://api.exa.ai/search",
            headers_builder=lambda k: {
                "x-api-key": k,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

    def _save_result(self, email, password, api_key):
        with BaseService._SAVE_LOCK:
            with open(self.output_file, "a", encoding="utf-8") as f:
                f.write(f"{email},EMAIL_OTP_ONLY,{api_key}\n")
