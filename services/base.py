import contextlib
import threading
from abc import ABC, abstractmethod

from patchright.sync_api import sync_playwright

import config


class BaseService(ABC):
    _SAVE_LOCK = threading.Lock()

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def signup_url(self) -> str:
        pass

    @property
    @abstractmethod
    def api_key_prefix(self) -> str:
        pass

    @property
    @abstractmethod
    def output_file(self) -> str:
        pass

    @property
    @abstractmethod
    def headless_config_key(self) -> str:
        pass

    def register(self, email, password):
        self._pre_register_hook()
        browser_cm = self._open_browser()
        browser = browser_cm.__enter__()
        try:
            page = browser.new_page()
            self._navigate_to_signup(page)
            self._fill_form(page, email, password)
            self._submit_form(page)
            self._verify_email(page, email)
            api_key = self._extract_api_key(page)
            self._do_post_verify(api_key)
            self._save_result(email, password, api_key)
            return api_key
        finally:
            try:
                browser_cm.__exit__(None, None, None)
            except Exception as teardown_exc:
                print(f"Browser cleanup warning: {teardown_exc}")

    def _pre_register_hook(self):
        pass

    def _do_post_verify(self, api_key):
        pass

    def _get_headless_setting(self):
        return getattr(config, self.headless_config_key, True)

    @abstractmethod
    def _navigate_to_signup(self, page):
        pass

    @abstractmethod
    def _fill_form(self, page, email, password):
        pass

    @abstractmethod
    def _submit_form(self, page):
        pass

    @abstractmethod
    def _verify_email(self, page, email):
        pass

    @abstractmethod
    def _extract_api_key(self, page):
        pass

    def _save_result(self, email, password, api_key):
        with BaseService._SAVE_LOCK:
            with open(self.output_file, "a", encoding="utf-8") as f:
                f.write(f"{email},{password},{api_key}\n")

    @contextlib.contextmanager
    def _open_browser(self):
        from proxy_manager import get_proxy_dict
        proxy = get_proxy_dict()
        headless = self._get_headless_setting()
        context_kwargs = {}
        if proxy:
            context_kwargs["proxy"] = {
                "server": proxy.get("server", ""),
                "username": proxy.get("username", ""),
                "password": proxy.get("password", ""),
            }
            print(f"Using proxy: {proxy.get('server', '')}")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            ctx = browser.new_context(**context_kwargs)
            try:
                yield ctx
            finally:
                ctx.close()
                browser.close()
