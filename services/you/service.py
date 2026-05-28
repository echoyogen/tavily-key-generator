import json
import re
import time

from services.base import BaseService
from services.common.browser import fill_first_input, extract_api_key_by_pattern


def _extract_you_api_key_from_response(body):
    if not body:
        return None

    try:
        data = json.loads(body)
    except Exception:
        data = None

    if data and isinstance(data, dict):
        for field in ("api_key", "apiKey", "key", "token", "access_token", "secret"):
            candidate = data.get(field)
            if candidate and isinstance(candidate, str) and len(candidate) >= 30:
                return candidate.strip()

        for value in data.values():
            if isinstance(value, dict):
                result = _extract_you_api_key_from_response(json.dumps(value))
                if result:
                    return result
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        result = _extract_you_api_key_from_response(json.dumps(item))
                        if result:
                            return result

    candidates = re.findall(r"[A-Za-z0-9_\-]{32,}", body)
    for candidate in candidates:
        if re.search(r"[a-zA-Z]", candidate) and re.search(r"[0-9]", candidate):
            return candidate

    return None


class YouService(BaseService):
    name = "you"
    signup_url = "https://you.com/"
    api_key_prefix = "you-"
    output_file = "you_accounts.txt"
    headless_config_key = "YOU_REGISTER_HEADLESS"

    def _navigate_to_signup(self, page):
        self._intercepted_keys = []

        def handle_response(response):
            url = response.url.lower()
            if "api.you.com" not in url and "you.com/api" not in url:
                return
            try:
                body = response.text()
            except Exception:
                return
            if not body:
                return
            key = _extract_you_api_key_from_response(body)
            if key:
                self._intercepted_keys.append(key)

        page.on("response", handle_response)

        page.goto("https://you.com/platform", wait_until="domcontentloaded", timeout=30000)
        time.sleep(2)

        signup_selectors = [
            'a:has-text("Sign up")',
            'a:has-text("Sign Up")',
            'a[href*="signup"]',
            'button:has-text("Sign up")',
            'button:has-text("Sign Up")',
        ]
        for selector in signup_selectors:
            if page.query_selector(selector):
                page.click(selector, no_wait_after=True)
                break

        time.sleep(2)

        email_option_selectors = [
            'a:has-text("Email")',
            'button:has-text("Email")',
            'a:has-text("email")',
            'button:has-text("email")',
        ]
        for selector in email_option_selectors:
            if page.query_selector(selector):
                page.click(selector, no_wait_after=True)
                break

        time.sleep(1)

    def _fill_form(self, page, email, password):
        email_selector = fill_first_input(
            page,
            ['input[type="email"]', 'input[placeholder*="email" i]', 'input[name="email"]'],
            email,
        )
        if not email_selector:
            print("Email input not found on you.com")
            return

        self._email_selector = email_selector

    def _submit_form(self, page):
        email_selector = getattr(self, "_email_selector", None)

        submitted = False
        for selector in ['button:has-text("Continue")', 'button:has-text("Submit")', 'button[type="submit"]']:
            if page.query_selector(selector):
                page.click(selector, no_wait_after=True)
                submitted = True
                break

        if not submitted and email_selector:
            page.press(email_selector, "Enter")

        try:
            page.wait_for_selector(
                'input[placeholder*="code" i], input[type="number"], input[placeholder*="verify" i], input[placeholder*="otp" i]',
                timeout=30000,
            )
        except Exception:
            print("OTP input not found on you.com")
            return

        print("Reached you.com OTP page")

    def _verify_email(self, page, email):
        from mail.factory import get_provider
        provider = get_provider()

        import config
        code = provider.get_email_code(email, timeout=config.EMAIL_CODE_TIMEOUT, service_hint="you")
        if not code:
            print("Failed to get OTP code for you.com")
            return

        otp_selector = fill_first_input(
            page,
            [
                'input[placeholder*="code" i]',
                'input[type="number"]',
                'input[placeholder*="verify" i]',
                'input[placeholder*="otp" i]',
            ],
            code,
        )
        if not otp_selector:
            print("OTP input field not found after code retrieval")
            return

        submitted = False
        for selector in [
            'button:has-text("Verify")',
            'button:has-text("Continue")',
            'button:has-text("Submit")',
            'button[type="submit"]',
        ]:
            if page.query_selector(selector):
                page.click(selector, no_wait_after=True)
                submitted = True
                break

        if not submitted:
            page.press(otp_selector, "Enter")

        try:
            page.wait_for_url("**/you.com/platform**", timeout=30000, wait_until="domcontentloaded")
        except Exception:
            print("Did not reach you.com platform dashboard after OTP")
            return

        print("you.com login successful")
        time.sleep(2)

        page.goto("https://you.com/platform/api-keys", wait_until="domcontentloaded", timeout=30000)
        time.sleep(2)

        for selector in [
            'button:has-text("Create")',
            'button:has-text("New")',
            'button:has-text("Generate")',
            'button:has-text("Create API Key")',
            'button:has-text("New API Key")',
        ]:
            if page.query_selector(selector):
                page.click(selector, no_wait_after=True)
                break

        time.sleep(1)

        fill_first_input(
            page,
            ['input[placeholder*="name" i]', 'input[name*="name" i]'],
            "auto-key",
        )

        for selector in [
            'button:has-text("Create")',
            'button:has-text("Confirm")',
            'button:has-text("Generate")',
            'button[type="submit"]',
        ]:
            if page.query_selector(selector):
                page.click(selector, no_wait_after=True)
                break

        time.sleep(2)

    def _extract_api_key(self, page):
        intercepted_keys = getattr(self, "_intercepted_keys", [])
        if intercepted_keys:
            api_key = intercepted_keys[-1]
            print("API key captured via network interception")
            return api_key

        dom_selectors = [
            'input[type="text"]',
            'code',
            '[data-testid*="key"]',
            'input[readonly]',
        ]
        for selector in dom_selectors:
            elements = page.query_selector_all(selector)
            for el in elements:
                try:
                    text = el.get_attribute("value") or el.inner_text()
                    if text and len(text) >= 30 and re.search(r"[A-Za-z0-9_\-]{30,}", text):
                        print(f"API key extracted from DOM ({selector})")
                        return text.strip()
                except Exception:
                    continue

        try:
            content = page.content()
            candidates = re.findall(r"[A-Za-z0-9_\-]{32,}", content)
            for candidate in candidates:
                if re.search(r"[a-zA-Z]", candidate) and re.search(r"[0-9]", candidate):
                    print("API key extracted from page content via regex")
                    return candidate
        except Exception:
            pass

        print("you.com API key not found")
        return None

    def _do_post_verify(self, api_key):
        import requests as std_requests
        import config
        try:
            response = std_requests.get(
                "https://api.you.com/v2/search",
                params={"query": "test", "num_web_results": 1},
                headers={
                    "X-API-Key": api_key,
                    "Accept": "application/json",
                },
                timeout=getattr(config, "API_KEY_TIMEOUT", 30),
            )
        except Exception as exc:
            print(f"API key verification request failed: {exc}")
            return

        if response.status_code == 200:
            print("API key verification passed")
            return

        preview = response.text.strip().replace("\n", " ")[:160]
        print(f"API key verification failed: HTTP {response.status_code}")
        if preview:
            print(f"   response: {preview}")

    def _save_result(self, email, password, api_key):
        with BaseService._SAVE_LOCK:
            with open(self.output_file, "a", encoding="utf-8") as f:
                f.write(f"{email},OTP_ONLY,{api_key}\n")
