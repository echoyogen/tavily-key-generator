import re
import time


def fill_first_input(page, selectors, value):
    for selector in selectors:
        if page.query_selector(selector):
            page.fill(selector, value)
            return selector
    return None


def click_first(page, selectors, timeout_ms=3000):
    for selector in selectors:
        if page.query_selector(selector):
            try:
                page.click(selector, timeout=timeout_ms)
                return selector
            except Exception:
                continue
    return None


def submit_form(page, input_selector=None):
    button_selectors = [
        'button[type="submit"]',
        'button:has-text("Sign up")',
        'button:has-text("Continue")',
        'button:has-text("Register")',
    ]

    for selector in button_selectors:
        if page.query_selector(selector):
            try:
                page.click(selector, timeout=3000)
                return True
            except Exception:
                continue

    if input_selector and page.query_selector(input_selector):
        try:
            page.press(input_selector, 'Enter')
            return True
        except Exception:
            return False

    return False


def extract_api_key_by_pattern(page, pattern):
    try:
        time.sleep(3)

        compiled = re.compile(pattern)

        selectors = [
            'code',
            '[data-testid*="key"]',
            '.api-key',
            'input[readonly]',
            'input[type="text"]',
        ]

        for selector in selectors:
            elements = page.query_selector_all(selector)
            for element in elements:
                try:
                    text = element.inner_text() or element.get_attribute('value') or ''
                except Exception:
                    text = ''
                match = compiled.search(text)
                if match:
                    return match.group(0)

        html = page.content()
        match = compiled.search(html)
        if match:
            return match.group(0)

        return None
    except Exception:
        return None


def attach_response_tracker(page, url_keywords):
    events = []

    def handle_response(response):
        url = response.url.lower()
        if not any(token in url for token in url_keywords):
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
