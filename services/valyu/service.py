import re
import time

from services.base import BaseService
from services.common.browser import fill_first_input, attach_response_tracker
from services.common.api_verifier import verify_api_key

_VALYU_KEY_RE = re.compile(r'val[a-z_]*[A-Za-z0-9_-]{20,}')


def _detect_signup_result(page, signup_events):
    snapshots = []
    current_url = page.url.lower()

    if "confirm-email" in current_url or "check-email" in current_url:
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

    for event in signup_events[-6:]:
        if event.get("status") == 422:
            body_lower = event.get("body", "").lower()
            return (
                "disposable_rejected",
                f"Supabase returned HTTP 422, possibly rejected disposable email domain: {body_lower[:200]}",
            )

    if "invalid email domain" in combined or ("email domain" in combined and "not allowed" in combined):
        return ("disposable_rejected", "valyu.ai (Supabase) rejected the email domain.")

    if "email already registered" in combined or "already registered" in combined or "user already registered" in combined:
        return ("exists", "This email is already registered.")

    success_markers = (
        "check your email",
        "confirmation link",
        "verify your email",
        "verification email",
        "email has been sent",
        "we sent you an email",
        "confirm your email",
    )
    if any(marker in combined for marker in success_markers):
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
    if "confirm-email" in current_url or "check-email" in current_url:
        return ("sent", "")

    return ("", "")


class ValyuService(BaseService):
    name = "valyu"
    signup_url = "https://www.valyu.network/"
    api_key_prefix = "valyu-"
    output_file = "valyu_accounts.txt"
    headless_config_key = "VALYU_REGISTER_HEADLESS"

    def _navigate_to_signup(self, page):
        self._signup_events = attach_response_tracker(
            page, ("signup", "auth", "register", "supabase")
        )

        print("Navigating to signup page...")
        page.goto("https://platform.valyu.ai/auth/signup", wait_until="networkidle", timeout=30000)
        time.sleep(2)

    def _fill_form(self, page, email, password):
        print("Filling registration form...")

        email_selector = fill_first_input(
            page,
            ['input[type="email"]', 'input[name="email"]'],
            email,
        )
        if not email_selector:
            print("Email input not found")
            return

        time.sleep(1)

        password_selector = fill_first_input(
            page,
            ['input[type="password"]', 'input[name="password"]'],
            password,
        )
        if not password_selector:
            print("Password input not found")
            return

        time.sleep(1)

        confirm_selector = page.query_selector(
            'input[name="confirmPassword"], input[placeholder*="confirm" i]'
        )
        if confirm_selector:
            confirm_selector.fill(password)
            time.sleep(1)

    def _submit_form(self, page):
        print("Submitting registration...")
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

        if not submitted:
            print("Submit button not found")
            return

        signup_events = getattr(self, "_signup_events", [])
        status, msg = _wait_for_signup_result(page, signup_events)

        if status == "disposable_rejected":
            print("Warning: valyu.ai (Supabase) rejected disposable email domain")
            return

        if status == "exists":
            if msg:
                print(f"Error: {msg}")
            return

        if status != "sent":
            for event in signup_events:
                if event.get("status") == 422:
                    print("Warning: valyu.ai (Supabase) rejected disposable email domain")
                    return
            if msg:
                print(f"Error: {msg}")

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
        if "platform.valyu.ai" not in current_url:
            print(f"Warning: Did not redirect to platform.valyu.ai after verification, current URL: {page.url}")
            time.sleep(3)

        print("Navigating to API keys page...")
        page.goto("https://platform.valyu.ai/user/account/apikeys", wait_until="networkidle", timeout=30000)
        time.sleep(3)

        create_selectors = [
            'button:has-text("Create")',
            'button:has-text("New API Key")',
            'button:has-text("Generate")',
            '[data-testid="create-api-key"]',
        ]
        for selector in create_selectors:
            if page.query_selector(selector):
                page.click(selector)
                time.sleep(2)
                name_input = page.query_selector('input[name="name"], input[placeholder*="name" i]')
                if name_input:
                    name_input.fill("auto-generated-key")
                    time.sleep(1)
                    for cs in [
                        'button:has-text("Create")',
                        'button:has-text("Generate")',
                        'button:has-text("Confirm")',
                        'button[type="submit"]',
                    ]:
                        if page.query_selector(cs):
                            page.click(cs)
                            time.sleep(3)
                            break
                break

    def _extract_api_key(self, page):
        print("Looking for API key...")
        try:
            time.sleep(3)

            selectors = [
                'input[type="text"]',
                'code',
                '[data-testid*="key"]',
                '.api-key',
                'input[readonly]',
            ]

            for selector in selectors:
                elements = page.query_selector_all(selector)
                for element in elements:
                    try:
                        text = element.inner_text() or element.get_attribute('value') or ''
                    except Exception:
                        text = ''
                    match = _VALYU_KEY_RE.search(text)
                    if match:
                        return match.group(0)

            html = page.content()
            matches = _VALYU_KEY_RE.findall(html)
            if matches:
                return matches[0]

            print("Error: Could not extract API key")
            return None
        except Exception as e:
            print(f"API key extraction failed: {e}")
            return None

    def _do_post_verify(self, api_key):
        result = verify_api_key(
            api_key,
            "https://api.valyu.ai/v1/search",
            lambda k: {"x-api-key": k, "Content-Type": "application/json"},
        )
        if result is False:
            print("Warning: API key verification failed, saving anyway")
        elif result is None:
            print("Warning: API key availability could not be confirmed (likely network issue), saving anyway")
