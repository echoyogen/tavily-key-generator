import time

from services.base import BaseService
from services.common.browser import (
    attach_response_tracker,
    extract_api_key_by_pattern,
    fill_first_input,
    submit_form,
)
from services.common.result_parser import wait_for_signup_result
from services.common.api_verifier import verify_api_key


class FirecrawlService(BaseService):
    name = "firecrawl"
    signup_url = "https://www.firecrawl.dev/"
    api_key_prefix = "fc-"
    output_file = "firecrawl_accounts.txt"
    headless_config_key = "FIRECRAWL_REGISTER_HEADLESS"

    def _navigate_to_signup(self, page):
        page.goto("https://firecrawl.dev/", wait_until="networkidle", timeout=30000)
        time.sleep(2)

        signup_selectors = [
            'a:has-text("Sign up")',
            'a:has-text("Sign Up")',
            'button:has-text("Sign up")',
            'a[href*="signup"]',
            'a[href*="register"]',
        ]

        for selector in signup_selectors:
            if page.query_selector(selector):
                page.click(selector)
                time.sleep(3)
                break

    def _fill_form(self, page, email, password):
        email_selector = fill_first_input(
            page,
            ['input[name="email"]', 'input[type="email"]', 'input[placeholder*="email" i]'],
            email,
        )
        if not email_selector:
            print("Email input not found")
            return

        time.sleep(1)

        fill_first_input(
            page,
            ['input[name="password"]', 'input[type="password"]'],
            password,
        )
        time.sleep(1)

    def _submit_form(self, page):
        self._signup_events = attach_response_tracker(
            page, ("signin", "signup", "auth", "clerk")
        )

        email_selector = page.query_selector('input[name="email"]') or page.query_selector('input[type="email"]')
        input_sel = None
        if email_selector:
            input_sel = 'input[type="email"]'

        submit_form(page, input_sel)

        status, message = wait_for_signup_result(page, self._signup_events)
        if status != "sent":
            if message:
                print(f"Signup failed: {message}")
            if status in {"blocked", "stalled"}:
                import config
                if config.FIRECRAWL_REGISTER_HEADLESS:
                    print("Tip: set FIRECRAWL_REGISTER_HEADLESS=false and retry with visible browser.")
                else:
                    print("Tip: switch to a cleaner network/proxy and retry.")

    def _verify_email(self, page, email):
        from mail.factory import get_provider
        provider = get_provider()

        import config
        verify_url = provider.get_verification_link(email, timeout=config.EMAIL_CODE_TIMEOUT)
        if not verify_url:
            print("Verification email not received")
            return

        page.goto(verify_url, wait_until="networkidle", timeout=60000)
        time.sleep(5)

        current_url = page.url.lower()
        if "login" in current_url or "signin" in current_url:
            fill_first_input(
                page,
                ['input[name="email"]', 'input[type="email"]'],
                email,
            )
            time.sleep(1)

            password_input = page.query_selector('input[name="password"]') or page.query_selector('input[type="password"]')
            if password_input:
                password_val = getattr(self, "_last_password", "")
                fill_first_input(
                    page,
                    ['input[name="password"]', 'input[type="password"]'],
                    password_val,
                )
                time.sleep(1)

            submit_form(page)
            time.sleep(5)

    def _extract_api_key(self, page):
        api_key = extract_api_key_by_pattern(page, r"fc-[a-zA-Z0-9_-]{20,}")
        if api_key:
            return api_key

        api_key_nav_selectors = [
            'a:has-text("API Keys")',
            'a[href*="api-key"]',
            'a[href*="apikey"]',
            'a[href*="keys"]',
            'button:has-text("API Keys")',
        ]

        found_nav = False
        for selector in api_key_nav_selectors:
            if page.query_selector(selector):
                page.click(selector)
                time.sleep(3)
                found_nav = True
                break

        if not found_nav:
            possible_urls = [
                "https://www.firecrawl.dev/app/api-keys",
                "https://www.firecrawl.dev/app/settings",
                "https://www.firecrawl.dev/app",
                "https://firecrawl.dev/dashboard/api-keys",
                "https://firecrawl.dev/api-keys",
                "https://app.firecrawl.dev/api-keys",
            ]
            for url in possible_urls:
                try:
                    page.goto(url, wait_until="networkidle", timeout=15000)
                    time.sleep(3)
                    if "api" in page.url.lower() and "key" in page.url.lower():
                        break
                except Exception:
                    continue

        return extract_api_key_by_pattern(page, r"fc-[a-zA-Z0-9_-]{20,}")

    def _do_post_verify(self, api_key):
        verify_api_key(
            api_key,
            "https://api.firecrawl.dev/v2/scrape",
            lambda k: {"Authorization": f"Bearer {k}"},
        )
