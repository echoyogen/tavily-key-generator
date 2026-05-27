import random
import re
import string
import time

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


class SerperService(BaseService):
    name = "serper"
    signup_url = "https://serper.dev/"
    api_key_prefix = "serper-"
    output_file = "serper_accounts.txt"
    headless_config_key = "SERPER_REGISTER_HEADLESS"

    def _navigate_to_signup(self, page):
        print("Navigating to signup page...")
        page.goto("https://serper.dev/signup", wait_until="networkidle", timeout=30000)
        time.sleep(2)

    def _fill_form(self, page, email, password):
        full_name = f"{_rand_str(5).capitalize()} {_rand_str(6).capitalize()}"
        print(f"Using name: {full_name}")

        fill_first_input(
            page,
            ['input[name="name"]', 'input[placeholder*="name" i]'],
            full_name,
        )
        time.sleep(0.5)

        email_selector = fill_first_input(
            page,
            ['input[type="email"]', 'input[name="email"]'],
            email,
        )
        if not email_selector:
            print("Error: Email input not found")
            return

        time.sleep(0.5)

        password_selector = fill_first_input(
            page,
            ['input[type="password"]', 'input[name="password"]'],
            password,
        )
        if not password_selector:
            print("Error: Password input not found")
            return

        time.sleep(0.5)
        self._email_selector = email_selector

    def _submit_form(self, page):
        self._signup_events = attach_response_tracker(
            page, ("signup", "register", "auth", "sign-up")
        )

        email_selector = getattr(self, "_email_selector", None)
        print("Submitting registration form...")

        submitted = False
        for selector in [
            'button[type="submit"]',
            'button:has-text("Sign up")',
            'button:has-text("Create Account")',
            'button:has-text("Register")',
        ]:
            if page.query_selector(selector):
                try:
                    page.click(selector, timeout=3000)
                    submitted = True
                    break
                except Exception:
                    continue

        if not submitted and email_selector:
            try:
                page.press(email_selector, "Enter")
            except Exception:
                pass

        status, msg = _wait_for_signup_result(page, self._signup_events)

        if status == "blocked":
            print(f"Warning: Registration blocked - {msg}")
            return

        if status in ("exists", "invalid_email"):
            print(f"Warning: {msg}")
            return

        if status != "sent":
            print("Error: Registration did not reach email verification step")

    def _verify_email(self, page, email):
        from mail.factory import get_provider
        provider = get_provider()

        import config
        print(f"Waiting for verification email (up to {config.EMAIL_CODE_TIMEOUT}s)...")
        verify_url = provider.get_verification_link(email, timeout=config.EMAIL_CODE_TIMEOUT)
        if not verify_url:
            print("Error: Verification email not received")
            return

        print(f"Received verification link: {verify_url[:50]}...")
        print("Navigating to verification link...")
        page.goto(verify_url, wait_until="networkidle", timeout=60000)
        time.sleep(5)

        current_url = page.url.lower()
        if "login" in current_url or "signin" in current_url:
            print("Login required after verification...")
            fill_first_input(
                page,
                ['input[type="email"]', 'input[name="email"]'],
                email,
            )
            time.sleep(0.5)

            password_val = getattr(self, "_last_password", "")
            fill_first_input(
                page,
                ['input[type="password"]', 'input[name="password"]'],
                password_val,
            )
            time.sleep(0.5)

            for selector in ['button[type="submit"]', 'button:has-text("Sign in")', 'button:has-text("Login")']:
                if page.query_selector(selector):
                    try:
                        page.click(selector, timeout=3000)
                        break
                    except Exception:
                        continue
            time.sleep(5)

        print("Navigating to API keys page...")
        for url in ["https://serper.dev/dashboard", "https://serper.dev/api-keys"]:
            try:
                page.goto(url, wait_until="networkidle", timeout=15000)
                time.sleep(3)
                break
            except Exception:
                continue

    def _extract_api_key(self, page):
        print("Extracting API key...")
        time.sleep(2)

        key_selectors = [
            "code",
            'input[type="text"][readonly]',
            ".api-key",
            '[data-testid*="key"]',
        ]

        for selector in key_selectors:
            elements = page.query_selector_all(selector)
            for element in elements:
                try:
                    text = element.inner_text() or element.get_attribute("value") or ""
                    match = re.search(r"[A-Za-z0-9]{32,}", text)
                    if match:
                        return match.group(0)
                except Exception:
                    continue

        html = page.content()
        matches = re.findall(r"[A-Za-z0-9]{32,}", html)
        if matches:
            return matches[0]

        print("Error: Could not extract API key")
        return None

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
