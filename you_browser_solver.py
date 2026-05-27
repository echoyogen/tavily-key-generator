import json
import os
import re
import threading
import time

import requests as std_requests
from camoufox.sync_api import Camoufox

from config import EMAIL_CODE_TIMEOUT, YOU_REGISTER_HEADLESS
from mail_provider import get_email_code

_HERE = os.path.dirname(os.path.abspath(__file__))
_SAVE_FILE = os.path.join(_HERE, "you_accounts.txt")
_SAVE_LOCK = threading.Lock()
_ACCOUNT_PASSWORD_LABEL = "OTP_ONLY"
_YOU_PLATFORM_URL = "https://you.com/platform"
_YOU_API_KEYS_URL = "https://you.com/platform/api-keys"


def fill_first_input(page, selectors, value):
    for selector in selectors:
        if page.query_selector(selector):
            page.fill(selector, value)
            return selector
    return None


def click_first(page, selectors):
    for selector in selectors:
        if page.query_selector(selector):
            page.click(selector, no_wait_after=True)
            return True
    return False


def extract_you_api_key_from_response(body):
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
                result = extract_you_api_key_from_response(json.dumps(value))
                if result:
                    return result
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        result = extract_you_api_key_from_response(json.dumps(item))
                        if result:
                            return result

    candidates = re.findall(r"[A-Za-z0-9_\-]{32,}", body)
    for candidate in candidates:
        if re.search(r"[a-zA-Z]", candidate) and re.search(r"[0-9]", candidate):
            return candidate

    return None


def save_account(email, api_key):
    with _SAVE_LOCK:
        with open(_SAVE_FILE, "a", encoding="utf-8") as file_obj:
            file_obj.write(f"{email},{_ACCOUNT_PASSWORD_LABEL},{api_key}\n")


def verify_api_key(api_key, timeout=30):
    try:
        response = std_requests.get(
            "https://api.you.com/v2/search",
            params={"query": "test", "num_web_results": 1},
            headers={
                "X-API-Key": api_key,
                "Accept": "application/json",
            },
            timeout=timeout,
        )
    except Exception as exc:
        print(f"API key verification request failed: {exc}")
        return False

    if response.status_code == 200:
        print("API key verification passed")
        return True

    preview = response.text.strip().replace("\n", " ")[:160]
    print(f"API key verification failed: HTTP {response.status_code}")
    if preview:
        print(f"   response: {preview}")
    return False


def register_with_browser(email, password):
    print(f"Registering you.com with browser: {email}")

    try:
        with Camoufox(headless=YOU_REGISTER_HEADLESS) as browser:
            page = browser.new_page()

            # Must register handler before any navigation so no responses are missed
            intercepted_keys = []

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
                key = extract_you_api_key_from_response(body)
                if key:
                    intercepted_keys.append(key)

            page.on("response", handle_response)

            page.goto(_YOU_PLATFORM_URL, wait_until="networkidle", timeout=30000)
            time.sleep(2)

            if not click_first(
                page,
                [
                    'a:has-text("Sign up")',
                    'a:has-text("Sign Up")',
                    'a[href*="signup"]',
                    'button:has-text("Sign up")',
                    'button:has-text("Sign Up")',
                ],
            ):
                print("Sign up link not found on you.com platform page")
                return None

            time.sleep(2)

            click_first(
                page,
                [
                    'a:has-text("Email")',
                    'button:has-text("Email")',
                    'a:has-text("email")',
                    'button:has-text("email")',
                ],
            )
            time.sleep(1)

            email_selector = fill_first_input(
                page,
                ['input[type="email"]', 'input[placeholder*="email" i]', 'input[name="email"]'],
                email,
            )
            if not email_selector:
                print("Email input not found on you.com")
                return None

            if not click_first(
                page,
                [
                    'button:has-text("Continue")',
                    'button:has-text("Submit")',
                    'button[type="submit"]',
                ],
            ):
                page.press(email_selector, "Enter")

            try:
                page.wait_for_selector(
                    'input[placeholder*="code" i], input[type="number"], input[placeholder*="verify" i], input[placeholder*="otp" i]',
                    timeout=30000,
                )
            except Exception:
                print("OTP input not found on you.com")
                return None

            print("Reached you.com OTP page")

            code = get_email_code(email, timeout=EMAIL_CODE_TIMEOUT, service="you")
            if not code:
                print("Failed to get OTP code for you.com")
                return None

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
                return None

            if not click_first(
                page,
                [
                    'button:has-text("Verify")',
                    'button:has-text("Continue")',
                    'button:has-text("Submit")',
                    'button[type="submit"]',
                ],
            ):
                page.press(otp_selector, "Enter")

            try:
                page.wait_for_url("**/you.com/platform**", timeout=30000, wait_until="domcontentloaded")
            except Exception:
                print("Did not reach you.com platform dashboard after OTP")
                return None

            print("you.com login successful")
            time.sleep(2)

            page.goto(_YOU_API_KEYS_URL, wait_until="networkidle", timeout=30000)
            time.sleep(2)

            click_first(
                page,
                [
                    'button:has-text("Create")',
                    'button:has-text("New")',
                    'button:has-text("Generate")',
                    'button:has-text("Create API Key")',
                    'button:has-text("New API Key")',
                ],
            )
            time.sleep(1)

            fill_first_input(
                page,
                ['input[placeholder*="name" i]', 'input[name*="name" i]'],
                "auto-key",
            )

            click_first(
                page,
                [
                    'button:has-text("Create")',
                    'button:has-text("Confirm")',
                    'button:has-text("Generate")',
                    'button[type="submit"]',
                ],
            )
            time.sleep(2)

            api_key = None

            if intercepted_keys:
                api_key = intercepted_keys[-1]
                print(f"API key captured via network interception")

            if not api_key:
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
                                api_key = text.strip()
                                print(f"API key extracted from DOM ({selector})")
                                break
                        except Exception:
                            continue
                    if api_key:
                        break

            if not api_key:
                try:
                    content = page.content()
                    candidates = re.findall(r"[A-Za-z0-9_\-]{32,}", content)
                    for candidate in candidates:
                        if re.search(r"[a-zA-Z]", candidate) and re.search(r"[0-9]", candidate):
                            api_key = candidate
                            print("API key extracted from page content via regex")
                            break
                except Exception:
                    pass

            if not api_key:
                print("you.com API key not found")
                return None

            print("Verifying API key...")
            if not verify_api_key(api_key):
                return None

            save_account(email, api_key)

            print("you.com registration successful")
            print(f"   email: {email}")
            print(f"   label: {_ACCOUNT_PASSWORD_LABEL}")
            print(f"   key  : {api_key}")
            return api_key

    except Exception as exc:
        print(f"you.com registration failed: {exc}")
        return None
