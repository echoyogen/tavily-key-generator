import random
import re
import string
import time

import requests

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


def _extract_csrf(html):
    """Extract CSRF token from HTML page. Returns None if not found."""
    import re as _re
    patterns = [
        r'<input[^>]*name=["\']_token["\'][^>]*value=["\']([^"\']+)["\']',
        r'<input[^>]*value=["\']([^"\']+)["\'][^>]*name=["\']_token["\']',
        r'<meta[^>]*name=["\']csrf-token["\'][^>]*content=["\']([^"\']+)["\']',
    ]
    for pat in patterns:
        m = _re.search(pat, html, _re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def _detect_http_signup_result(resp):
    """Detect the result of an HTTP signup response. Returns: 'sent', 'exists', 'blocked', or 'unknown'."""
    combined = (resp.text or "").lower()
    final_url = (getattr(resp, "url", "") or "").lower()

    if "verify-email" in final_url or "check-email" in final_url:
        return "sent"
    if "check your email" in combined or "verify your email" in combined or "verification email" in combined:
        return "sent"
    if "already registered" in combined or "email already exists" in combined or "already in use" in combined:
        return "exists"
    if "cannot register at this time" in combined or "blocked" in combined:
        return "blocked"
    return "unknown"


def _extract_serper_key(html):
    """Extract a Serper API key (32 alphanumeric chars) from HTML."""
    import re as _re
    matches = _re.findall(r"[A-Za-z0-9]{32,}", html)
    if matches:
        return matches[0]
    return None


class SerperService(BaseService):
    name = "serper"
    signup_url = "https://serper.dev/"
    api_key_prefix = "serper-"
    output_file = "serper_accounts.txt"
    headless_config_key = "SERPER_REGISTER_HEADLESS"

    def register(self, email, password):
        """HTTP primary path. Falls back to _browser_fallback on any error."""
        import config
        from mail.factory import get_provider

        sess = requests.Session()
        headers = {"User-Agent": _HTTP_UA, "Referer": "https://serper.dev/"}
        try:
            # Step 1: GET signup page and extract CSRF token (if any)
            signup_page = sess.get("https://serper.dev/signup", headers=headers, timeout=15)
            csrf_token = _extract_csrf(signup_page.text)

            # Step 2: POST signup form
            full_name = f"{_rand_str(5).capitalize()} {_rand_str(6).capitalize()}"
            form_data = {"name": full_name, "email": email, "password": password}
            if csrf_token:
                form_data["_token"] = csrf_token
            resp = sess.post(
                "https://serper.dev/signup",
                data=form_data,
                headers={**headers, "Content-Type": "application/x-www-form-urlencoded"},
                allow_redirects=True,
                timeout=15,
            )

            # Step 3: detect signup result
            status = _detect_http_signup_result(resp)
            if status not in ("sent", "exists"):
                raise RuntimeError(f"Signup failed with status: {status}, body: {resp.text[:200]}")

            # Step 4: wait for verification link
            verify_link = get_provider().get_verification_link(email, timeout=config.EMAIL_CODE_TIMEOUT)
            if not verify_link:
                raise RuntimeError("No verification email received")

            # Step 5: follow verification link
            sess.get(verify_link, allow_redirects=True, headers=headers, timeout=60)

            # Step 6: navigate to dashboard and extract API key
            api_key = None
            for url in ["https://serper.dev/dashboard", "https://serper.dev/api-keys"]:
                r = sess.get(url, allow_redirects=True, headers=headers, timeout=15)
                api_key = _extract_serper_key(r.text)
                if api_key:
                    break
            if not api_key:
                raise RuntimeError("Could not extract API key from dashboard")

            self._do_post_verify(api_key)
            self._save_result(email, password, api_key)
            return api_key
        except Exception as e:
            print(f"[serper] HTTP flow error: {e}, falling back to browser")
            return self._browser_fallback(email, password)

    def _browser_fallback(self, email, password):
        """Browser fallback: executes full browser-based registration flow."""
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
        result = verify_api_key(
            api_key,
            "https://google.serper.dev/search",
            lambda k: {"X-API-KEY": k, "Content-Type": "application/json"},
        )
        if result is False:
            print("Warning: API key verification failed, saving anyway")
        elif result is None:
            print("Warning: API key availability could not be confirmed (likely network issue), saving anyway")
