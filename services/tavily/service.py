import contextlib
import re
import time

import requests as std_requests
from patchright.sync_api import sync_playwright

from config import (
    API_KEY_TIMEOUT,
    EMAIL_CODE_TIMEOUT,
    LOCAL_SOLVER_URL,
)
from mail.factory import get_provider as _get_mail_provider
from services.base import BaseService
from services.common.api_verifier import verify_api_key as _verify_key
from services.common.browser import extract_api_key_by_pattern, fill_first_input

TURNSTILE_SITEKEY = "0x4AAAAAAAQFNSW6xordsuIq"


def _solve_turnstile(url, sitekey=TURNSTILE_SITEKEY):
    try:
        r = std_requests.get(
            f"{LOCAL_SOLVER_URL}/turnstile",
            params={"url": url, "sitekey": sitekey or TURNSTILE_SITEKEY},
            timeout=10,
        )
        if r.status_code != 200:
            print(f"Solver request failed: {r.status_code}")
            return None

        task_id = r.json().get("taskId")
        if not task_id:
            print("No task ID from solver")
            return None

        for _ in range(60):
            time.sleep(2)
            res = std_requests.get(
                f"{LOCAL_SOLVER_URL}/result",
                params={"id": task_id},
                timeout=10,
            )
            if res.status_code == 200:
                data = res.json()
                status = data.get("status")
                if status == "ready":
                    token = data.get("solution", {}).get("token")
                    if token:
                        return token
                elif status == "CAPTCHA_FAIL":
                    return None

        return None
    except Exception as exc:
        print(f"Solver error: {exc}")
        return None


def _inject_turnstile_token(page, token):
    safe_token = token.replace("\\", "\\\\").replace("'", "\\'")
    script = f"""
    (function() {{
        const token = '{safe_token}';
        const form = document.querySelector('form') || document.body;
        const names = ['captcha', 'cf-turnstile-response'];

        const ensureField = (name) => {{
            let field = document.querySelector(`input[name="${{name}}"], textarea[name="${{name}}"]`);
            if (field) {{
                return field;
            }}
            field = document.createElement(name.includes('response') ? 'textarea' : 'input');
            if (field.tagName === 'INPUT') {{
                field.type = 'hidden';
            }}
            field.name = name;
            form.appendChild(field);
            return field;
        }};

        names.forEach((name) => {{
            const field = ensureField(name);
            field.value = token;
            field.dispatchEvent(new Event('input', {{ bubbles: true }}));
            field.dispatchEvent(new Event('change', {{ bubbles: true }}));
        }});

        if (typeof window._turnstileTokenCallback === 'function') {{
            window._turnstileTokenCallback(token);
        }}
        if (typeof window.turnstileCallback === 'function') {{
            window.turnstileCallback(token);
        }}
        return true;
    }})();
    """
    return page.evaluate(script)


def _get_turnstile_sitekey(page):
    try:
        sitekey = page.evaluate(
            """
            () => {
                const node = document.querySelector(
                    '[data-captcha-sitekey], .cf-turnstile, [data-sitekey]'
                );
                if (!node) {
                    return '';
                }
                return (
                    node.getAttribute('data-captcha-sitekey') ||
                    node.getAttribute('data-sitekey') ||
                    ''
                );
            }
            """
        )
    except Exception:
        sitekey = ""

    if sitekey:
        return sitekey.strip()

    html = page.content()
    match = re.search(
        r'(?:data-captcha-sitekey|data-sitekey)=["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()

    return TURNSTILE_SITEKEY


def _submit_primary_action(page, input_selector=None):
    button_selectors = [
        'button[data-action-button-primary="true"]',
        'button[type="submit"][name="action"][value="default"]:not([aria-hidden="true"])',
        'button[type="submit"]:not([aria-hidden="true"])',
    ]
    for selector in button_selectors:
        if page.query_selector(selector):
            try:
                page.click(selector, no_wait_after=True, timeout=3000)
                return True
            except Exception:
                continue

    if input_selector and page.query_selector(input_selector):
        try:
            page.press(input_selector, "Enter")
            return True
        except Exception:
            return False

    return False


def _extract_page_feedback(page):
    selectors = [
        '[role="alert"]',
        '[data-error-visible="true"]',
        '.ulp-input-error-message',
        '.auth0-global-message',
        '.cf-turnstile-error',
    ]
    messages = []
    for selector in selectors:
        for node in page.query_selector_all(selector):
            text = (node.inner_text() or "").strip()
            if text and text not in messages:
                messages.append(text)
    return " | ".join(messages)


def _wait_for_post_signup_target(page, timeout):
    deadline = time.time() + (timeout / 1000)
    while time.time() < deadline:
        current_url = page.url.lower()
        if (
            "app.tavily.com" in current_url
            or "/verify" in current_url
            or "/continue" in current_url
        ):
            return True
        time.sleep(0.5)
    return False


def _collect_turnstile_state(page):
    try:
        state = page.evaluate(
            """
            () => {
                const passwordInput = document.querySelector('input[name="password"]');
                const widget = document.querySelector(
                    'div[data-captcha-sitekey], .cf-turnstile, [data-sitekey]'
                );
                const iframe = document.querySelector(
                    'iframe[src*="challenges.cloudflare.com"], iframe[src*="turnstile"]'
                );
                const captchaInput = document.querySelector(
                    'input[name="captcha"], input[name="cf-turnstile-response"], textarea[name="cf-turnstile-response"]'
                );
                return {
                    hasCaptchaDiv: !!widget,
                    hasChallengeIframe: !!iframe,
                    hasCaptchaInput: !!captchaInput,
                    hasTurnstile: typeof window.turnstile !== 'undefined',
                    hasPasswordInput: !!passwordInput,
                    passwordValueLength: passwordInput ? passwordInput.value.length : 0,
                    sitekey: widget
                        ? (widget.getAttribute('data-captcha-sitekey') || widget.getAttribute('data-sitekey') || '')
                        : '',
                };
            }
            """
        )
    except Exception:
        state = {}

    return {
        "hasCaptchaDiv": bool(state.get("hasCaptchaDiv")),
        "hasChallengeIframe": bool(state.get("hasChallengeIframe")),
        "hasCaptchaInput": bool(state.get("hasCaptchaInput")),
        "hasTurnstile": bool(state.get("hasTurnstile")),
        "hasPasswordInput": bool(state.get("hasPasswordInput")),
        "passwordValueLength": int(state.get("passwordValueLength") or 0),
        "sitekey": (state.get("sitekey") or "").strip(),
    }


def _normalize_feedback(feedback):
    return (feedback or "").replace("\u2019", "'").strip().lower()


def _has_password_challenge_signal(feedback=None, state=None):
    lowered = _normalize_feedback(feedback)
    if any(
        keyword in lowered
        for keyword in (
            "security challenge",
            "captcha",
            "turnstile",
            "cloudflare",
            "couldn't load the security challenge",
        )
    ):
        return True

    state = state or {}
    return any(
        (
            state.get("hasCaptchaDiv"),
            state.get("hasChallengeIframe"),
            state.get("hasCaptchaInput"),
            state.get("hasTurnstile"),
        )
    )


def _format_turnstile_state(state):
    return (
        f"captchaDiv={'Y' if state.get('hasCaptchaDiv') else 'N'}, "
        f"iframe={'Y' if state.get('hasChallengeIframe') else 'N'}, "
        f"input={'Y' if state.get('hasCaptchaInput') else 'N'}, "
        f"turnstile={'Y' if state.get('hasTurnstile') else 'N'}, "
        f"pwdLen={state.get('passwordValueLength', 0)}"
    )


def _refill_password(page, password):
    selector = 'input[name="password"]'
    if not page.query_selector(selector):
        return False
    page.fill(selector, password)
    return True


def _refresh_password_page_if_needed(page, feedback, state):
    lowered = _normalize_feedback(feedback)
    if "couldn't load the security challenge" not in lowered:
        return False

    if state.get("hasChallengeIframe") or state.get("hasTurnstile"):
        return False

    print("Detected security challenge load failure, refreshing password page...")
    try:
        page.reload(wait_until="networkidle", timeout=30000)
        page.wait_for_selector('input[name="password"]', timeout=15000)
        time.sleep(2)
        return True
    except Exception as exc:
        print(f"Password page refresh failed: {exc}")
        return False


def _wait_for_password_challenge_ready(page, timeout=8):
    deadline = time.time() + timeout
    latest_state = {}
    while time.time() < deadline:
        latest_state = _collect_turnstile_state(page)
        if latest_state.get("hasChallengeIframe") or latest_state.get("hasTurnstile"):
            return latest_state
        time.sleep(0.5)
    return latest_state


def _ensure_password_challenge_ready(page):
    state = _wait_for_password_challenge_ready(page, timeout=6)
    if not state.get("hasPasswordInput"):
        return state

    if state.get("hasChallengeIframe") or state.get("hasTurnstile"):
        return state

    if state.get("hasCaptchaDiv") or state.get("hasCaptchaInput"):
        print("Password page challenge not fully rendered, refreshing...")
        try:
            page.reload(wait_until="networkidle", timeout=30000)
            page.wait_for_selector('input[name="password"]', timeout=15000)
            time.sleep(2)
            state = _wait_for_password_challenge_ready(page, timeout=6)
        except Exception as exc:
            print(f"Password page pre-refresh failed: {exc}")

    return state


def _recover_password_challenge(page, password, max_attempts=3):
    print("Password page did not redirect, handling security challenge...")

    for attempt in range(1, max_attempts + 1):
        if _wait_for_post_signup_target(page, timeout=5000):
            return True

        time.sleep(2)
        feedback = _extract_page_feedback(page)
        state = _collect_turnstile_state(page)

        print(f"Password page recovery attempt {attempt}/{max_attempts}")
        print(f"   DOM: {_format_turnstile_state(state)}")
        if feedback:
            print(f"   Hint: {feedback}")

        if _wait_for_post_signup_target(page, timeout=2000):
            return True

        if _refresh_password_page_if_needed(page, feedback, state):
            feedback = _extract_page_feedback(page)
            state = _collect_turnstile_state(page)
            print(f"   After refresh DOM: {_format_turnstile_state(state)}")
            if feedback:
                print(f"   After refresh hint: {feedback}")

            if _wait_for_post_signup_target(page, timeout=2000):
                return True

        if _has_password_challenge_signal(feedback, state):
            sitekey = state.get("sitekey") or _get_turnstile_sitekey(page)
            print(f"Attempting to recover Turnstile challenge (sitekey={sitekey})")
            token = _solve_turnstile(page.url, sitekey=sitekey)
            if token:
                if _inject_turnstile_token(page, token):
                    print("Injected password page challenge token")
                else:
                    print("Token obtained but injection unconfirmed, continuing resubmit")
            else:
                print("Password page challenge token failed, continuing normal resubmit")
        else:
            print("No explicit challenge DOM detected, executing delayed resubmit")

        if not _refill_password(page, password):
            if _wait_for_post_signup_target(page, timeout=5000):
                return True
            print("Password input lost, cannot continue recovery")
            return False

        time.sleep(1)
        _submit_primary_action(page, 'input[name="password"]')
        time.sleep(4)

    return _wait_for_post_signup_target(page, timeout=5000)


def _submit_password_with_recovery(page, password):
    initial_state = _ensure_password_challenge_ready(page)
    if initial_state:
        print(f"Password page challenge state: {_format_turnstile_state(initial_state)}")

    if not _refill_password(page, password):
        return False

    time.sleep(1)
    _submit_primary_action(page, 'input[name="password"]')
    time.sleep(5)

    if _wait_for_post_signup_target(page, timeout=15000):
        return True

    return _recover_password_challenge(page, password)


def _close_marketing_dialog(page):
    close_button = page.query_selector('button[aria-label="Close"]')
    if close_button:
        close_button.click()
        time.sleep(1)


def _wait_for_api_key(page, timeout=20):
    start_time = time.time()
    while time.time() - start_time < timeout:
        _close_marketing_dialog(page)
        html = page.content()
        api_key_matches = re.findall(r"tvly-[a-zA-Z0-9_-]{20,}", html)
        api_keys = [k for k in api_key_matches if k != "tvly-YOUR_API_KEY"]
        if api_keys:
            return max(api_keys, key=len)
        time.sleep(1)
    return None


class TavilyService(BaseService):
    name = "tavily"
    signup_url = "https://app.tavily.com/sign-up"
    api_key_prefix = "tvly-"
    output_file = "accounts.txt"
    headless_config_key = "TAVILY_REGISTER_HEADLESS"

    def _pre_register_hook(self):
        try:
            r = std_requests.get(f"{LOCAL_SOLVER_URL}/", timeout=1)
            if r.status_code == 200:
                return
        except Exception:
            pass
        raise RuntimeError("Turnstile solver 未就绪，请先启动")

    @contextlib.contextmanager
    def _open_browser(self):
        headless = self._get_headless_setting()
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            ctx = browser.new_context()
            try:
                yield ctx
            finally:
                ctx.close()
                browser.close()

    def register(self, email, password):
        """HTTP primary path. _pre_register_hook() must NOT be inside try/except."""
        self._pre_register_hook()  # OUTSIDE try -- solver not ready = direct raise, no fallback

        from mail.factory import get_provider
        sess = std_requests.Session()
        try:
            # Step 1: solve Turnstile for signup page
            signup_url = "https://auth.tavily.com/u/signup"
            token = _solve_turnstile(signup_url, TURNSTILE_SITEKEY)
            if not token:
                raise RuntimeError("Turnstile solve failed")

            # Step 2: POST Auth0 signup
            r = sess.post(
                "https://auth.tavily.com/dbconnections/signup",
                json={
                    "client_id": "RRIAvvXNFxpfTWIozX1mXqLnyUmYSTrQ",
                    "email": email,
                    "password": password,
                    "connection": "Username-Password-Authentication",
                    "captcha": token,
                },
                headers={"User-Agent": "Mozilla/5.0", "Origin": "https://app.tavily.com"},
                timeout=30,
            )
            if r.status_code not in (200, 201):
                if r.status_code != 409:  # 409 = already exists, try login anyway
                    raise RuntimeError(f"Auth0 signup failed: {r.status_code} {r.text[:200]}")

            # Step 3: wait for verification email
            verify_link = get_provider().get_verification_link(email, timeout=EMAIL_CODE_TIMEOUT)
            if not verify_link:
                raise RuntimeError("Verification email not received")

            # Step 4: follow verification link
            sess.get(
                verify_link,
                allow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=60,
            )
            time.sleep(3)

            # Step 5: access dashboard and extract key
            api_key = None
            for url in ["https://app.tavily.com/account/api-keys", "https://app.tavily.com/app"]:
                r2 = sess.get(url, allow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
                time.sleep(2)
                keys = re.findall(r"tvly-[a-zA-Z0-9_-]{20,}", r2.text)
                keys = [k for k in keys if k != "tvly-YOUR_API_KEY"]
                if keys:
                    api_key = max(keys, key=len)
                    break
            if not api_key:
                raise RuntimeError("No tvly- key found in dashboard HTML")

            self._do_post_verify(api_key)
            self._save_result(email, password, api_key)
            return api_key
        except Exception as e:
            print(f"[tavily] HTTP flow error: {e}, falling back to browser")
            return self._browser_fallback(email, password)

    def _browser_fallback(self, email, password):
        """Browser fallback: executes full patchright-based registration flow."""
        try:
            browser_cm = self._open_browser()
            browser = browser_cm.__enter__()
            try:
                page = browser.new_page()

                # --- _navigate_to_signup ---
                page.goto("https://app.tavily.com/sign-in", wait_until="domcontentloaded", timeout=30000)
                time.sleep(2)
                html = page.content()
                match = re.search(r'href="(/u/signup/identifier[^"]*)"', html)
                if match:
                    nav_signup_url = f"https://auth.tavily.com{match.group(1)}"
                    print("Navigating to signup page...")
                    page.goto(nav_signup_url, wait_until="domcontentloaded", timeout=30000)
                    time.sleep(2)
                else:
                    selectors = [
                        'input[name="username"]',
                        'input[name="email"]',
                        'input[type="email"]',
                    ]
                    has_email_input = any(page.query_selector(s) for s in selectors)
                    has_continue = any(
                        page.query_selector(s)
                        for s in (
                            'button[type="submit"]',
                            'button:has-text("Continue")',
                            'button:has-text("Sign Up")',
                        )
                    )
                    if has_email_input and has_continue:
                        print("Detected unified login/signup entry, using current page...")
                    else:
                        print(f"Signup entry not found: {page.url}")

                # --- _fill_form ---
                email_selector = fill_first_input(
                    page, ['input[name="email"]', 'input[name="username"]'], email
                )
                if not email_selector:
                    print("Email input not found on signup page")
                    return None

                print("Handling signup page Turnstile...")
                token1 = _solve_turnstile(page.url, sitekey=_get_turnstile_sitekey(page))
                if not token1:
                    print("Token acquisition failed")
                    return None
                print(f"Token: {token1[:50]}...")

                if _inject_turnstile_token(page, token1):
                    print("Token injected")
                else:
                    print("captcha input not found")

                _submit_primary_action(page, email_selector)
                time.sleep(6)

                try:
                    page.wait_for_selector('input[name="code"], input[name="password"]', timeout=15000)
                except Exception:
                    print("First submit did not redirect, retrying Continue...")
                    _submit_primary_action(page)
                    time.sleep(3)
                    try:
                        page.wait_for_selector('input[name="code"], input[name="password"]', timeout=20000)
                    except Exception:
                        feedback = _extract_page_feedback(page)
                        print(f"Did not reach verification/password page: {page.url}")
                        if feedback:
                            print(f"   Page hint: {feedback}")
                        return None

                if page.query_selector('input[name="code"]'):
                    print("Reached email verification code page")
                    code = _get_mail_provider().get_email_code(email, timeout=EMAIL_CODE_TIMEOUT, service_hint="tavily")
                    if not code:
                        return None
                    page.fill('input[name="code"]', code)
                    _submit_primary_action(page, 'input[name="code"]')
                    time.sleep(3)

                try:
                    page.wait_for_selector('input[name="password"]', timeout=30000)
                    print("Reached password page")
                except Exception:
                    print(f"Did not reach password page: {page.url}")
                    return None

                # --- _submit_form ---
                if not _submit_password_with_recovery(page, password):
                    feedback = _extract_page_feedback(page)
                    print(f"Login failed: {page.url}")
                    if feedback:
                        print(f"   Page hint: {feedback}")

                # --- _verify_email ---
                print("Checking for additional email verification...")
                time.sleep(3)
                if "verify" in page.url.lower():
                    print("Email verification required")
                    verify_url = _get_mail_provider().get_verification_link(email, timeout=60)
                    if verify_url:
                        page.goto(verify_url, wait_until="domcontentloaded", timeout=60000)
                        page.wait_for_url("**/app.tavily.com/**", timeout=60000)
                        time.sleep(3)

                # --- _extract_api_key ---
                print("Extracting API key...")
                time.sleep(3)
                api_key = _wait_for_api_key(page, timeout=API_KEY_TIMEOUT)
                if not api_key:
                    api_key = extract_api_key_by_pattern(page, r"tvly-[a-zA-Z0-9_-]+")

                self._do_post_verify(api_key)
                self._save_result(email, password, api_key)
                return api_key
            finally:
                try:
                    browser_cm.__exit__(None, None, None)
                except Exception as e:
                    print(f"[tavily] Browser cleanup: {e}")
        except Exception as e:
            print(f"[tavily] Browser fallback failed: {e}")
            return None

    def _navigate_to_signup(self, page):
        raise NotImplementedError("TavilyService uses HTTP-primary flow")

    def _fill_form(self, page, email, password):
        raise NotImplementedError("TavilyService uses HTTP-primary flow")

    def _submit_form(self, page):
        raise NotImplementedError("TavilyService uses HTTP-primary flow")

    def _verify_email(self, page, email):
        raise NotImplementedError("TavilyService uses HTTP-primary flow")

    def _extract_api_key(self, page):
        raise NotImplementedError("TavilyService uses HTTP-primary flow")

    def _do_post_verify(self, api_key):
        if not api_key:
            return
        _verify_key(
            api_key,
            endpoint="https://api.tavily.com/search",
            headers_builder=lambda k: {"Authorization": f"Bearer {k}", "Content-Type": "application/json"},
            json_body={"query": "test", "max_results": 1},
        )
