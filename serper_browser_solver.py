import os
import re
import random
import string
import threading
import time
import requests as std_requests
from camoufox.sync_api import Camoufox
from config import (
    API_KEY_TIMEOUT,
    EMAIL_CODE_TIMEOUT,
    SERPER_REGISTER_HEADLESS,
)
from mail_provider import get_verification_link

_HERE = os.path.dirname(os.path.abspath(__file__))
_SAVE_FILE = os.path.join(_HERE, "serper_accounts.txt")
_SAVE_LOCK = threading.Lock()
_SERPER_SIGNUP_RESULT_TIMEOUT = 15


def rand_str(length):
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


def attach_signup_feedback_tracker(page):
    events = []

    def handle_response(response):
        url = response.url.lower()
        if not any(token in url for token in ("signup", "register", "auth", "sign-up")):
            return

        try:
            body = response.text()
        except Exception:
            body = ""

        events.append(
            {
                "url": response.url,
                "status": response.status,
                "body": body[:1500],
            }
        )

    page.on("response", handle_response)
    return events


def detect_signup_result(page, signup_events):
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
        return (
            "blocked",
            "Serper.dev blocked registration: Cannot Register at this time.",
        )

    if "already registered" in combined or "email already exists" in combined:
        return ("exists", "This email address is already registered.")

    if "invalid email" in combined:
        return ("invalid_email", "Serper.dev considers this email address invalid.")

    if "check your email" in combined or "verify your email" in combined or "verification email" in combined:
        return ("sent", "")

    return ("", "")


def wait_for_signup_result(page, signup_events, timeout=_SERPER_SIGNUP_RESULT_TIMEOUT):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, message = detect_signup_result(page, signup_events)
        if status:
            return status, message
        time.sleep(1)

    current_url = page.url.lower()
    if "verify-email" in current_url or "check-email" in current_url:
        return ("sent", "")

    return ("", "")


def fill_first_input(page, selectors, value):
    for selector in selectors:
        if page.query_selector(selector):
            page.fill(selector, value)
            return selector
    return None


def save_account(email, password, api_key):
    with _SAVE_LOCK:
        with open(_SAVE_FILE, "a", encoding="utf-8") as f:
            f.write(f"{email},{password},{api_key}\n")


def verify_api_key(api_key, timeout=API_KEY_TIMEOUT):
    transient_errors = (
        std_requests.exceptions.SSLError,
        std_requests.exceptions.ConnectionError,
        std_requests.exceptions.Timeout,
    )
    last_error = None

    for attempt in range(1, 4):
        try:
            response = std_requests.post(
                "https://google.serper.dev/search",
                json={"q": "test"},
                headers={
                    "X-API-KEY": api_key,
                    "Content-Type": "application/json",
                },
                timeout=timeout,
            )
            break
        except transient_errors as exc:
            last_error = exc
            if attempt < 3:
                print(f"Warning: API key test encountered network/TLS error, retrying ({attempt}/3): {exc}")
                time.sleep(attempt)
                continue
            print(f"Warning: API key test failed after retries, cannot confirm key validity: {exc}")
            print("   This is typically caused by local proxy/TUN/DNS hijacking, not necessarily an invalid key.")
            return None
        except Exception as exc:
            print(f"Error: API key test failed: {exc}")
            return False
    else:
        print(f"Warning: API key test did not get a valid response: {last_error}")
        return None

    if response.status_code == 200:
        print("API key test passed")
        return True

    preview = response.text.strip().replace("\n", " ")[:160]
    print(f"Error: API key test failed: HTTP {response.status_code}")
    if preview:
        print(f"   Response: {preview}")
    return False


def register_with_browser(email, password):
    print(f"Registering serper.dev account: {email}")

    try:
        with Camoufox(headless=SERPER_REGISTER_HEADLESS) as browser:
            page = browser.new_page()
            signup_events = attach_signup_feedback_tracker(page)

            print("Navigating to signup page...")
            page.goto("https://serper.dev/signup", wait_until="networkidle", timeout=30000)
            time.sleep(2)

            full_name = f"{rand_str(5).capitalize()} {rand_str(6).capitalize()}"
            print(f"Using name: {full_name}")

            name_selector = fill_first_input(
                page,
                ['input[name="name"]', 'input[placeholder*="name" i]'],
                full_name,
            )
            if not name_selector:
                print("Warning: Name input not found, continuing without it")
            time.sleep(0.5)

            email_selector = fill_first_input(
                page,
                ['input[type="email"]', 'input[name="email"]'],
                email,
            )
            if not email_selector:
                print("Error: Email input not found")
                return None
            time.sleep(0.5)

            password_selector = fill_first_input(
                page,
                ['input[type="password"]', 'input[name="password"]'],
                password,
            )
            if not password_selector:
                print("Error: Password input not found")
                return None
            time.sleep(0.5)

            print("Submitting registration form...")
            submit_selectors = [
                'button[type="submit"]',
                'button:has-text("Sign up")',
                'button:has-text("Create Account")',
                'button:has-text("Register")',
            ]
            submitted = False
            for selector in submit_selectors:
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
                    submitted = True
                except Exception:
                    pass

            status, msg = wait_for_signup_result(page, signup_events)

            if status == "blocked":
                print(f"Warning: Registration blocked - {msg}")
                return None

            if status in ("exists", "invalid_email"):
                print(f"Warning: {msg}")
                return None

            if status != "sent":
                print("Error: Registration did not reach email verification step")
                return None

            print(f"Waiting for verification email (up to {EMAIL_CODE_TIMEOUT}s)...")
            verify_url = get_verification_link(email, timeout=EMAIL_CODE_TIMEOUT)
            if not verify_url:
                print("Error: Verification email not received")
                return None

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
                fill_first_input(
                    page,
                    ['input[type="password"]', 'input[name="password"]'],
                    password,
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
            api_key = None

            for url in ["https://serper.dev/dashboard", "https://serper.dev/api-keys"]:
                try:
                    page.goto(url, wait_until="networkidle", timeout=15000)
                    time.sleep(3)
                    break
                except Exception:
                    continue

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
                        # serper API keys are alphanumeric strings of 32+ chars
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

            if not api_key:
                print("Error: Could not extract API key")
                return None

            print(f"Found API key: {api_key[:20]}...")

            print("Verifying API key...")
            verify_result = verify_api_key(api_key)
            if verify_result is False:
                print("Warning: API key verification failed, saving anyway")
            elif verify_result is None:
                print("Warning: API key availability could not be confirmed (likely network issue), saving anyway")

            save_account(email, password, api_key)

            print(f"Registration successful")
            print(f"   Email   : {email}")
            print(f"   Password: {password}")
            print(f"   Key     : {api_key}")
            return api_key

    except Exception as e:
        print(f"Error: Registration failed: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    from mail_provider import create_email
    email, password = create_email(service="serper")
    register_with_browser(email, password)
