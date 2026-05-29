"""
ValyuService — HTTP 主路径 + 浏览器 Fallback

认证链路：
  1. GET  platform.valyu.ai/auth (warm-up，Cloudflare cookie 设置)
  2. GET  platform.valyu.ai/onboarding?email=...&provider=email (提取 next-action ID)
  3. POST platform.valyu.ai/onboarding?email=...&provider=email (Server Action，触发验证邮件)
       → 失败时降级: POST auth.valyu.ai/auth/v1/signup (Supabase 直连)
  4. 收取验证邮件中的 magic link (mail provider)
  5. GET  验证链接 (auth.valyu.ai/auth/v1/verify?token=...)，跟随重定向到 platform
  6. POST auth.valyu.ai/auth/v1/token?grant_type=password (密码登录，获取 access_token)
  7. GET  platform.valyu.ai/user/account/apikeys (提取或创建 API key)
  → 全链路失败时: Camoufox 浏览器完成 11 步 onboarding
"""

import html as _html_mod
import random
import re
import string
import time

import requests

import config
from services.base import BaseService

# 常量
SUPABASE_URL = "https://auth.valyu.ai"
SUPABASE_ANON_KEY = "sb_publishable_8AbrTfadTWE6iBwyjzK2TA_mJJbL0G6"
PLATFORM_URL = "https://platform.valyu.ai"
_FALLBACK_ACTION_ID = "4049b0f006c0cc849cd70fb479842ca0d4c4bbade9"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
_VALYU_KEY_RE = re.compile(r'val[a-z_]*[A-Za-z0-9_-]{20,}')

# 名字池和选项池（tuple，不可变全局状态）
_FIRST_NAMES = (
    "James", "Emma", "Liam", "Olivia", "Noah", "Ava", "William", "Sophia",
    "Benjamin", "Isabella", "Lucas", "Mia", "Henry", "Charlotte", "Alexander",
    "David", "Sarah", "Michael", "Emily", "Daniel", "Jessica", "Matthew",
    "Ashley", "Andrew", "Hannah", "Ryan", "Samantha", "Kevin", "Rachel",
)
_LAST_NAMES = (
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark",
)
_HEARD_FROM = (
    "linkedin", "twitter", "reddit", "search", "github", "friend", "other",
)
_ROLES = (
    "ai_developer", "non_ai_developer", "founder_cto", "vibe_coder", "researcher", "other",
)
_INDUSTRIES = (
    "technology", "finance", "healthcare", "education", "research", "media_entertainment", "other",
)
_TECHNOLOGIES = (
    "ai_sdk", "openai_sdk", "langchain", "mcp", "n8n", "non_technical",
)

# Header 字典
_NAV_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "user-agent": _UA,
}
_SUPABASE_HEADERS = {
    "accept": "application/json",
    "apikey": SUPABASE_ANON_KEY,
    "content-type": "application/json",
    "user-agent": _UA,
}
_PLATFORM_CORS_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "origin": PLATFORM_URL,
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": _UA,
}


class ValyuService(BaseService):
    name = "valyu"
    signup_url = "https://platform.valyu.ai/auth"
    api_key_prefix = "valyu-"
    output_file = "valyu_accounts.txt"
    headless_config_key = "VALYU_REGISTER_HEADLESS"

    # ------------------------------------------------------------------
    # 主入口 (Task 6)
    # ------------------------------------------------------------------

    def register(self, email, password):
        pass  # Task 6

    # ------------------------------------------------------------------
    # HTTP 初始化组 (Task 2)
    # ------------------------------------------------------------------

    def _warm_up(self, sess):
        pass  # Task 2

    def _get_onboarding_page_html(self, sess, email):
        pass  # Task 2

    def _submit_onboarding(self, sess, email, password):
        pass  # Task 2

    def _supabase_signup_fallback(self, sess, email, password):
        pass  # Task 2

    # ------------------------------------------------------------------
    # 验证组 (Task 3)
    # ------------------------------------------------------------------

    def _wait_and_verify_email(self, email):
        pass  # Task 3

    def _verify_via_link(self, sess, link):
        pass  # Task 3

    def _password_login(self, sess, email, password):
        pass  # Task 3

    # ------------------------------------------------------------------
    # Key 获取组 (Task 4)
    # ------------------------------------------------------------------

    def _extract_valyu_key(self, text):
        pass  # Task 4

    def _fetch_api_key_http(self, sess, access_token):
        pass  # Task 4

    def _do_post_verify(self, api_key):
        pass  # Task 4

    def _save_result(self, email, password, api_key):
        pass  # Task 4

    # ------------------------------------------------------------------
    # 浏览器 fallback (Task 5)
    # ------------------------------------------------------------------

    def _browser_fallback(self, email, password):
        pass  # Task 5

    # ------------------------------------------------------------------
    # Abstract method stubs (Task 5)
    # ------------------------------------------------------------------

    def _open_browser(self):
        raise NotImplementedError("ValyuService uses HTTP-primary flow; _browser_fallback() handles browser path directly")

    def _navigate_to_signup(self, page):
        raise NotImplementedError("ValyuService uses HTTP-primary flow; _browser_fallback() handles browser path directly")

    def _fill_form(self, page, email, password):
        raise NotImplementedError("ValyuService uses HTTP-primary flow; _browser_fallback() handles browser path directly")

    def _submit_form(self, page):
        raise NotImplementedError("ValyuService uses HTTP-primary flow; _browser_fallback() handles browser path directly")

    def _verify_email(self, page, email):
        raise NotImplementedError("ValyuService uses HTTP-primary flow; _browser_fallback() handles browser path directly")

    def _extract_api_key(self, page):
        raise NotImplementedError("ValyuService uses HTTP-primary flow; _browser_fallback() handles browser path directly")
