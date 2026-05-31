import json
import random
import re
import string
import time

import requests
from patchright.sync_api import sync_playwright

from services.base import BaseService
from services.common.browser import fill_first_input, submit_form, attach_response_tracker
from services.common.api_verifier import verify_api_key


def _rand_str(length):
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


def _detect_signup_result(page, signup_events):
    snapshots = []
    current_url = page.url.lower()

    if "verify-email" in current_url or "check-email" in current_url:
        return ("sent", "")

    try:
        snapshots.append(page.locator("body").inner_text())
    except Exception:
        pass

    try:
        snapshots.append(page.content())
    except Exception:
        pass

    snapshots.extend(event.get("body", "") for event in signup_events[-6:])
    combined = "\n".join(snapshots).lower()

    if "cannot register at this time" in combined:
        return ("blocked", "Serper.dev blocked registration: Cannot Register at this time.")

    if "already registered" in combined or "email already exists" in combined:
        return ("exists", "This email address is already registered.")

    if "invalid email" in combined:
        return ("invalid_email", "Serper.dev considers this email address invalid.")

    if "check your email" in combined or "verify your email" in combined or "verification email" in combined:
        return ("sent", "")

    return ("", "")


def _wait_for_signup_result(page, signup_events, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, message = _detect_signup_result(page, signup_events)
        if status:
            return status, message
        time.sleep(1)

    current_url = page.url.lower()
    if "verify-email" in current_url or "check-email" in current_url:
        return ("sent", "")

    return ("", "")


_HTTP_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"


def _intercept_form_submission(page_url, route_pattern, form_filler, timeout=90):
    """
    Open page_url with patchright, intercept route_pattern request,
    call form_filler(page) to trigger form submission, abort the real request,
    and return the captured request body as a dict.
    Raises RuntimeError("captcha solve timeout") if timeout is exceeded.
    """
    captured = {}

    def _handler(route):
        try:
            raw = route.request.post_data
            if raw:
                captured["body"] = json.loads(raw)
        except Exception:
            captured["body"] = {}
        finally:
            try:
                route.abort()
            except Exception:
                pass

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.route(route_pattern, _handler)
            page.goto(page_url, wait_until="networkidle", timeout=60000)
            form_filler(page)
            deadline = time.time() + timeout
            while time.time() < deadline:
                if captured.get("body") is not None:
                    return captured["body"]
                time.sleep(0.5)
            raise RuntimeError("captcha solve timeout")
        finally:
            browser.close()


def _fill_signup_form(page, email, password, first_name, last_name):
    try:
        for sel in ['input[name="firstName"]', 'input[placeholder*="first" i]']:
            el = page.query_selector(sel)
            if el:
                el.fill(first_name)
                break
    except Exception:
        pass
    try:
        for sel in ['input[name="lastName"]', 'input[placeholder*="last" i]']:
            el = page.query_selector(sel)
            if el:
                el.fill(last_name)
                break
    except Exception:
        pass
    try:
        for sel in ['input[type="email"]', 'input[name="email"]']:
            el = page.query_selector(sel)
            if el:
                el.fill(email)
                break
    except Exception:
        pass
    try:
        for sel in ['input[type="password"]', 'input[name="password"]', 'input[name="password1"]']:
            el = page.query_selector(sel)
            if el:
                el.fill(password)
                break
    except Exception:
        pass
    time.sleep(2)
    try:
        for sel in ['button[type="submit"]', 'button:has-text("Sign up")', 'button:has-text("Create Account")', 'button:has-text("Register")']:
            el = page.query_selector(sel)
            if el:
                el.click()
                break
    except Exception:
        pass


def _fill_login_form(page, email, password):
    try:
        for sel in ['input[type="email"]', 'input[name="email"]']:
            el = page.query_selector(sel)
            if el:
                el.fill(email)
                break
    except Exception:
        pass
    try:
        for sel in ['input[type="password"]', 'input[name="password"]']:
            el = page.query_selector(sel)
            if el:
                el.fill(password)
                break
    except Exception:
        pass
    time.sleep(2)
    try:
        for sel in ['button[type="submit"]', 'button:has-text("Sign in")', 'button:has-text("Login")']:
            el = page.query_selector(sel)
            if el:
                el.click()
                break
    except Exception:
        pass


class SerperService(BaseService):
    name = "serper"
    signup_url = "https://serper.dev/"
    api_key_prefix = "serper-"
    output_file = "serper_accounts.txt"
    headless_config_key = "SERPER_REGISTER_HEADLESS"

    def register(self, email, password):
        import config
        from mail.factory import get_provider

        try:
            first_name = _rand_str(5).capitalize()
            last_name = _rand_str(6).capitalize()

            # Step A: use patchright to open signup page, intercept /auth/register, get dual tokens
            signup_body = _intercept_form_submission(
                page_url="https://serper.dev/signup",
                route_pattern="**/auth/register",
                form_filler=lambda page: _fill_signup_form(page, email, password, first_name, last_name),
                timeout=90,
            )
            recaptcha_token = signup_body.get("recaptchaToken", "")
            turnstile_token = signup_body.get("turnstileToken", "")
            if not recaptcha_token or not turnstile_token:
                raise RuntimeError(f"captcha tokens missing from intercepted body: {signup_body}")

            # Step B: HTTP registration
            sess = requests.Session()
            resp = sess.post(
                "https://api.serper.dev/auth/register",
                json={
                    "email": email,
                    "password": password,
                    "firstName": first_name,
                    "lastName": last_name,
                    "recaptchaToken": recaptcha_token,
                    "turnstileToken": turnstile_token,
                },
                headers={
                    "Origin": "https://serper.dev",
                    "Referer": "https://serper.dev/signup",
                    "Content-Type": "application/json",
                    "User-Agent": _HTTP_UA,
                },
                timeout=30,
            )
            if resp.status_code >= 400:
                body_text = resp.text[:300]
                if "Captcha is invalid" in resp.text:
                    raise RuntimeError("captcha rejected by server")
                if "error.unique.email" in resp.text or "already" in resp.text.lower():
                    raise RuntimeError("email already exists")
                raise RuntimeError(f"register failed {resp.status_code}: {body_text}")

            # Step C: wait for verification email, extract token
            verify_link = get_provider().get_verification_link(email, timeout=config.EMAIL_CODE_TIMEOUT)
            if not verify_link:
                raise RuntimeError("No verification email received")
            m = re.search(r'confirm-email\?token=([A-Za-z0-9._\-]+)', verify_link)
            if not m:
                raise RuntimeError(f"Could not extract verify token from link: {verify_link}")
            verify_token = m.group(1)

            # Step D: HTTP email verification
            resp = sess.post(
                "https://api.serper.dev/users/verify-email",
                json={"token": verify_token},
                headers={
                    "Origin": "https://serper.dev",
                    "Content-Type": "application/json",
                    "User-Agent": _HTTP_UA,
                },
                timeout=15,
            )
            if resp.status_code >= 400:
                raise RuntimeError(f"email verify failed {resp.status_code}: {resp.text[:200]}")

            # Step E: use patchright to open login page, intercept /auth/login, get login turnstile token
            login_body = _intercept_form_submission(
                page_url="https://serper.dev/login",
                route_pattern="**/auth/login",
                form_filler=lambda page: _fill_login_form(page, email, password),
                timeout=90,
            )
            login_turnstile_token = login_body.get("turnstileToken", "")
            if not login_turnstile_token:
                raise RuntimeError(f"login turnstile token missing: {login_body}")

            # Step F: HTTP login
            resp = sess.post(
                "https://api.serper.dev/auth/login",
                json={
                    "email": email,
                    "password": password,
                    "turnstileToken": login_turnstile_token,
                },
                headers={
                    "Origin": "https://serper.dev",
                    "Referer": "https://serper.dev/login",
                    "Content-Type": "application/json",
                    "User-Agent": _HTTP_UA,
                },
                timeout=15,
            )
            if resp.status_code >= 400:
                raise RuntimeError(f"login failed {resp.status_code}: {resp.text[:200]}")
            login_data = resp.json()
            if login_data.get("isTwoFactorEnabled"):
                raise NotImplementedError("2FA not supported")

            # Step G: get or create API key
            resp = sess.get(
                "https://api.serper.dev/users/api-keys",
                headers={
                    "Origin": "https://serper.dev",
                    "User-Agent": _HTTP_UA,
                },
                timeout=15,
            )
            api_key = None
            if resp.status_code == 200:
                keys = resp.json().get("data", [])
                if keys:
                    k = keys[0]
                    api_key = k.get("key") or k.get("apiKey") or k.get("value")
            if not api_key:
                resp = sess.post(
                    "https://api.serper.dev/users/api-keys",
                    json={"name": "default"},
                    headers={
                        "Origin": "https://serper.dev",
                        "Content-Type": "application/json",
                        "User-Agent": _HTTP_UA,
                    },
                    timeout=15,
                )
                if resp.status_code < 400:
                    data = resp.json()
                    api_key = data.get("key") or data.get("apiKey") or data.get("value")

            # Step H: return
            if not api_key:
                raise RuntimeError("api key not found in response")

            self._do_post_verify(api_key)
            self._save_result(email, password, api_key)
            return api_key

        except Exception as e:
            print(f"[serper] HTTP flow error: {e}, falling back to browser")
            return self._browser_fallback(email, password)

    def _browser_fallback(self, email, password):
        try:
            browser_cm = BaseService._open_browser(self)
            browser = browser_cm.__enter__()
            try:
                page = browser.new_page()
                # --- from _navigate_to_signup ---
                page.goto("https://serper.dev/signup", wait_until="domcontentloaded", timeout=30000)
                time.sleep(2)
                # --- from _fill_form ---
                full_name = f"{_rand_str(5).capitalize()} {_rand_str(6).capitalize()}"
                fill_first_input(page, ['input[name="name"]', 'input[placeholder*="name" i]'], full_name)
                time.sleep(0.5)
                email_selector = fill_first_input(page, ['input[type="email"]', 'input[name="email"]'], email)
                if not email_selector:
                    print("[serper] Error: Email input not found")
                time.sleep(0.5)
                password_selector = fill_first_input(page, ['input[type="password"]', 'input[name="password"]'], password)
                time.sleep(0.5)
                # --- from _submit_form ---
                signup_events = attach_response_tracker(page, ("signup", "register", "auth", "sign-up"))
                submitted = False
                for selector in ['button[type="submit"]', 'button:has-text("Sign up")', 'button:has-text("Create Account")', 'button:has-text("Register")']:
                    if page.query_selector(selector):
                        try:
                            page.click(selector, timeout=3000)
                            submitted = True
                            break
                        except Exception:
                            continue
                if not submitted and email_selector:
                    try: page.press(email_selector, "Enter")
                    except Exception: pass
                status, msg = _wait_for_signup_result(page, signup_events)
                if status in ("blocked", "exists", "invalid_email"):
                    print(f"[serper] Warning: {msg}")
                elif status != "sent":
                    print("[serper] Registration did not reach email verification step")
                # --- from _verify_email ---
                from mail.factory import get_provider
                import config
                verify_url = get_provider().get_verification_link(email, timeout=config.EMAIL_CODE_TIMEOUT)
                if verify_url:
                    page.goto(verify_url, wait_until="domcontentloaded", timeout=60000)
                    time.sleep(5)
                    current_url = page.url.lower()
                    if "login" in current_url or "signin" in current_url:
                        fill_first_input(page, ['input[type="email"]', 'input[name="email"]'], email)
                        time.sleep(0.5)
                        fill_first_input(page, ['input[type="password"]', 'input[name="password"]'], password)
                        time.sleep(0.5)
                        for sel in ['button[type="submit"]', 'button:has-text("Sign in")', 'button:has-text("Login")']:
                            if page.query_selector(sel):
                                try: page.click(sel, timeout=3000); break
                                except Exception: continue
                        time.sleep(5)
                    for url in ["https://serper.dev/dashboard", "https://serper.dev/api-keys"]:
                        try: page.goto(url, wait_until="domcontentloaded", timeout=15000); time.sleep(3); break
                        except Exception: continue
                # --- from _extract_api_key ---
                api_key = None
                time.sleep(2)
                for selector in ["code", 'input[type="text"][readonly]', ".api-key", '[data-testid*="key"]']:
                    elements = page.query_selector_all(selector)
                    for element in elements:
                        try:
                            text = element.inner_text() or element.get_attribute("value") or ""
                            match = re.search(r"[A-Za-z0-9]{32,}", text)
                            if match:
                                api_key = match.group(0)
                                break
                        except Exception:
                            continue
                    if api_key:
                        break
                if not api_key:
                    html = page.content()
                    matches = re.findall(r"[A-Za-z0-9]{32,}", html)
                    if matches:
                        api_key = matches[0]
                self._do_post_verify(api_key)
                self._save_result(email, password, api_key)
                return api_key
            finally:
                try: browser_cm.__exit__(None, None, None)
                except Exception as e: print(f"[serper] Browser cleanup: {e}")
        except Exception as e:
            print(f"[serper] Browser fallback failed: {e}")
            return None

    def _navigate_to_signup(self, page):
        page.goto("https://serper.dev/signup", wait_until="domcontentloaded", timeout=30000)
        time.sleep(2)

    def _fill_form(self, page, email, password):
        raise NotImplementedError

    def _submit_form(self, page):
        raise NotImplementedError

    def _verify_email(self, page, email):
        from mail.factory import get_provider
        provider = get_provider()

        import config
        verify_url = provider.get_verification_link(email, timeout=config.EMAIL_CODE_TIMEOUT)
        if not verify_url:
            return

        page.goto(verify_url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(5)

        current_url = page.url.lower()
        if "login" in current_url or "signin" in current_url:
            fill_first_input(page, ['input[type="email"]', 'input[name="email"]'], email)
            time.sleep(0.5)
            password_val = getattr(self, "_last_password", "")
            fill_first_input(page, ['input[type="password"]', 'input[name="password"]'], password_val)
            time.sleep(0.5)
            for selector in ['button[type="submit"]', 'button:has-text("Sign in")', 'button:has-text("Login")']:
                if page.query_selector(selector):
                    try:
                        page.click(selector, timeout=3000)
                        break
                    except Exception:
                        continue
            time.sleep(5)

        for url in ["https://serper.dev/dashboard", "https://serper.dev/api-keys"]:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
                time.sleep(3)
                break
            except Exception:
                continue

    def _extract_api_key(self, page):
        raise NotImplementedError

    def _do_post_verify(self, api_key):
        if not api_key:
            return
        result = verify_api_key(
            api_key,
            "https://google.serper.dev/search",
            lambda k: {"X-API-KEY": k, "Content-Type": "application/json"},
            json_body={"q": "test"},
        )
        if result is False:
            print("Warning: API key verification failed, saving anyway")
        elif result is None:
            print("Warning: API key availability could not be confirmed (likely network issue), saving anyway")
