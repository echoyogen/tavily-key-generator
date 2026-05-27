"""
使用 Camoufox 完成 valyu.ai 注册
valyu.ai 使用 Supabase Email+Password 认证，需要邮件确认链接
"""
import os
import re
import threading
import time
import requests as std_requests
from camoufox.sync_api import Camoufox
from config import (
    EMAIL_CODE_TIMEOUT,
    VALYU_REGISTER_HEADLESS,
)
from mail_provider import get_verification_link

_HERE = os.path.dirname(os.path.abspath(__file__))
_SAVE_FILE = os.path.join(_HERE, "valyu_accounts.txt")
_SAVE_LOCK = threading.Lock()
_VALYU_SIGNUP_RESULT_TIMEOUT = 15

# valyu.ai API key regex: val_ prefix or valyu_ prefix, at least 20 chars after prefix
_VALYU_KEY_RE = re.compile(r'val[a-z_]*[A-Za-z0-9_-]{20,}')


def fill_first_input(page, selectors, value):
    """Fill the first existing input element matching any of the selectors."""
    for selector in selectors:
        if page.query_selector(selector):
            page.fill(selector, value)
            return selector
    return None


def detect_signup_result(page, signup_events):
    """Determine signup submission result from page content and network responses."""
    snapshots = []
    current_url = page.url.lower()

    # Check URL for confirmation redirect
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

    # Check for disposable email rejection (HTTP 422 from Supabase)
    for event in signup_events[-6:]:
        if event.get("status") == 422:
            body_lower = event.get("body", "").lower()
            return (
                "disposable_rejected",
                f"Supabase 返回 HTTP 422，可能拒绝了临时邮件域名: {body_lower[:200]}",
            )

    if "invalid email domain" in combined or "email domain" in combined and "not allowed" in combined:
        return (
            "disposable_rejected",
            "valyu.ai (Supabase) 拒绝了该邮件域名，可能是临时邮件域名。",
        )

    if "email already registered" in combined or "already registered" in combined or "user already registered" in combined:
        return ("exists", "这个邮箱已经注册过了。")

    # Check for successful email confirmation sent
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


def wait_for_signup_result(page, signup_events, timeout=_VALYU_SIGNUP_RESULT_TIMEOUT):
    """Poll for signup result until timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, message = detect_signup_result(page, signup_events)
        if status:
            return status, message
        time.sleep(1)

    current_url = page.url.lower()
    if "confirm-email" in current_url or "check-email" in current_url:
        return ("sent", "")

    return ("", "")


def save_account(email, password, api_key):
    """Thread-safe append to valyu_accounts.txt."""
    with _SAVE_LOCK:
        with open(_SAVE_FILE, 'a', encoding='utf-8') as f:
            f.write(f"{email},{password},{api_key}\n")


def extract_valyu_api_key(page):
    """Extract valyu API key from the current page."""
    try:
        time.sleep(3)

        # Try DOM element selectors first
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

        # Fall back to full page HTML
        html = page.content()
        matches = _VALYU_KEY_RE.findall(html)
        if matches:
            return matches[0]

        return None
    except Exception as e:
        print(f"⚠️  提取 API Key 失败: {e}")
        return None


def verify_api_key(api_key, timeout=30):
    """Verify valyu API key via POST to /v1/search with lowercase x-api-key header."""
    transient_errors = (
        std_requests.exceptions.SSLError,
        std_requests.exceptions.ConnectionError,
        std_requests.exceptions.Timeout,
    )
    last_error = None

    for attempt in range(1, 4):
        try:
            response = std_requests.post(
                "https://api.valyu.ai/v1/search",
                json={
                    "query": "test",
                    "max_num_results": 1,
                },
                headers={
                    "x-api-key": api_key,
                    "Content-Type": "application/json",
                },
                timeout=timeout,
            )
            break
        except transient_errors as exc:
            last_error = exc
            if attempt < 3:
                print(f"⚠️  API Key 调用测试遇到网络/TLS 异常，正在重试 ({attempt}/3): {exc}")
                time.sleep(attempt)
                continue
            print(f"⚠️  API Key 调用测试遇到网络/TLS 异常，暂时无法确认 Key 是否可用: {exc}")
            print("   这通常是本地代理 / TUN / DNS 劫持链路导致的瞬时握手失败，不一定代表 Key 无效。")
            return None
        except Exception as exc:
            print(f"❌ API Key 调用测试失败: {exc}")
            return False
    else:
        print(f"⚠️  API Key 调用测试未获得有效响应: {last_error}")
        return None

    if response.status_code == 200:
        print("✅ API Key 调用测试通过")
        return True

    preview = response.text.strip().replace("\n", " ")[:160]
    print(f"❌ API Key 调用测试失败: HTTP {response.status_code}")
    if preview:
        print(f"   响应: {preview}")
    return False


def register_with_browser(email, password):
    """Register a valyu.ai account using browser automation."""
    print(f"🌐 使用浏览器模式注册 valyu.ai: {email}")

    try:
        with Camoufox(headless=VALYU_REGISTER_HEADLESS) as browser:
            page = browser.new_page()

            # Set up network interception to capture 422 responses (disposable email rejection)
            signup_events = []

            def handle_response(response):
                url = response.url.lower()
                if any(t in url for t in ("signup", "auth", "register", "supabase")):
                    try:
                        signup_events.append({
                            "url": response.url,
                            "status": response.status,
                            "body": response.text()[:500],
                        })
                    except Exception:
                        signup_events.append({
                            "url": response.url,
                            "status": response.status,
                            "body": "",
                        })

            page.on("response", handle_response)

            # 1. Navigate to signup page
            print("🧭 进入注册页...")
            page.goto("https://platform.valyu.ai/auth/signup", wait_until="networkidle", timeout=30000)
            time.sleep(2)

            # 2. Fill registration form
            print("📝 填写注册信息...")

            # Fill email
            email_selector = fill_first_input(
                page,
                ['input[type="email"]', 'input[name="email"]'],
                email,
            )
            if not email_selector:
                print("❌ 未找到邮箱输入框")
                return None

            time.sleep(1)

            # Fill password
            password_selector = fill_first_input(
                page,
                ['input[type="password"]', 'input[name="password"]'],
                password,
            )
            if not password_selector:
                print("❌ 未找到密码输入框")
                return None

            time.sleep(1)

            # Fill confirm password if present
            confirm_selector = page.query_selector(
                'input[name="confirmPassword"], input[placeholder*="confirm" i]'
            )
            if confirm_selector:
                confirm_selector.fill(password)
                time.sleep(1)

            # 3. Submit form
            print("📤 提交注册...")
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

            if not submitted:
                print("❌ 未找到提交按钮")
                return None

            # 4. Wait for signup result
            status, msg = wait_for_signup_result(page, signup_events)

            if status == "disposable_rejected":
                print("⚠️ valyu.ai (Supabase) 拒绝了临时邮件域名，建议配置自定义域名")
                return None

            if status == "exists":
                if msg:
                    print(f"❌ {msg}")
                return None

            if status != "sent":
                # Check signup_events for any 422 status
                for event in signup_events:
                    if event.get("status") == 422:
                        print("⚠️ valyu.ai (Supabase) 拒绝了临时邮件域名，建议配置自定义域名")
                        return None
                if msg:
                    print(f"❌ {msg}")
                return None

            # 5. Wait for verification email
            print(f"📧 等待邮箱验证链接（最多 {EMAIL_CODE_TIMEOUT} 秒）...")
            verify_url = get_verification_link(email, timeout=EMAIL_CODE_TIMEOUT)
            if not verify_url:
                print("❌ 未收到验证邮件")
                return None

            print(f"✅ 收到验证链接: {verify_url[:50]}...")

            # 6. Navigate to verification link
            print("🔗 访问验证链接...")
            page.goto(verify_url, wait_until="networkidle", timeout=60000)
            time.sleep(5)

            # 7. Wait for platform.valyu.ai
            current_url = page.url.lower()
            if "platform.valyu.ai" not in current_url:
                print(f"⚠️  验证后未跳转到 platform.valyu.ai，当前 URL: {page.url}")
                time.sleep(3)

            # 8. Navigate to API keys page
            print("🔑 导航到 API Keys 页面...")
            page.goto("https://platform.valyu.ai/user/account/apikeys", wait_until="networkidle", timeout=30000)
            time.sleep(3)

            # 9. Click Create button if present
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
                    # Fill name if asked
                    name_input = page.query_selector('input[name="name"], input[placeholder*="name" i]')
                    if name_input:
                        name_input.fill("auto-generated-key")
                        time.sleep(1)
                        # Confirm creation
                        confirm_selectors = [
                            'button:has-text("Create")',
                            'button:has-text("Generate")',
                            'button:has-text("Confirm")',
                            'button[type="submit"]',
                        ]
                        for cs in confirm_selectors:
                            if page.query_selector(cs):
                                page.click(cs)
                                time.sleep(3)
                                break
                    break

            # 10. Extract API key
            print("🔍 查找 API Key...")
            api_key = extract_valyu_api_key(page)

            if not api_key:
                print("❌ 无法获取 API Key")
                return None

            print(f"✅ 获取到 API Key: {api_key[:20]}...")

            # 11. Verify API key
            print("🧪 验证 API Key 可用性...")
            verify_result = verify_api_key(api_key)
            if verify_result is False:
                print("⚠️  API Key 验证失败，但仍然保存")
            elif verify_result is None:
                print("⚠️  API Key 可用性暂时无法确认，但更像是网络/TLS 问题，仍然保存")

            save_account(email, password, api_key)

            print(f"🎉 注册成功")
            print(f"   邮箱: {email}")
            print(f"   密码: {password}")
            print(f"   Key : {api_key}")
            return api_key

    except Exception as e:
        print(f"❌ 注册失败: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    from mail_provider import create_email
    email, password = create_email(service="valyu")
    register_with_browser(email, password)
