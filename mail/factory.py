"""
邮件工厂模块。
- 邮件服务商配置从数据库（mail_providers 表）加载，不再读取 .env
- 每次 create_email() 调用通过同步桥接查询 DB，选取第一个 enabled 的 provider
- OnlineMailProvider 仍保持进程内单例（_mailbox_cache 需跨调用共享）
- 对外接口与原版完全兼容：create_email(service) / get_provider() / set_domain()
"""
from __future__ import annotations

import asyncio
import json
import random
import string
import threading
from typing import Optional

from mail.cloudflare import CloudflareProvider
from mail.duckmail import DuckMailProvider
from mail.onlinemail import OnlineMailProvider

_SUPPORTED_SERVICES = ("tavily", "firecrawl", "exa", "you", "serper", "valyu")

# ─── 进程内缓存 ───────────────────────────────────────────────────────────────
# OnlineMailProvider 必须单例（_mailbox_cache 需跨 create/verify 调用共享）
_onlinemail_instances: dict[int, OnlineMailProvider] = {}  # provider_id -> instance
_instance_lock = threading.Lock()

# 手动覆盖 domain（set_domain() 调用时生效）
_SELECTED_DOMAIN = ""


def set_domain(domain: str):
    global _SELECTED_DOMAIN
    _SELECTED_DOMAIN = (domain or "").strip()


# ─── DB 同步桥接 ──────────────────────────────────────────────────────────────

def _run_async(coro):
    """在已有 event loop 的线程中安全地运行协程（用于从注册线程访问 DB）。"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 在工作线程中：通过 run_coroutine_threadsafe 提交到主 loop
            # 注：此路径仅在 web worker 线程中触发
            future = asyncio.run_coroutine_threadsafe(coro, loop)
            return future.result(timeout=10)
        else:
            return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


async def _load_active_provider_row():
    """从 DB 读取第一个 enabled 的 MailProvider 行。"""
    from web.database import get_session_factory
    from web.models import MailProvider
    from sqlalchemy import select

    factory = get_session_factory()
    async with factory() as session:
        row = (await session.execute(
            select(MailProvider).where(MailProvider.enabled == True).limit(1)
        )).scalar_one_or_none()
        if row is None:
            return None
        # 把需要的字段提取成普通 dict，避免 lazy-load session 关闭后访问
        return {
            "id": row.id,
            "provider_type": row.provider_type,
            "config_json": row.config_json,
            "orders_pool": row.orders_pool,
        }


async def _pop_onlinemail_order(provider_id: int, service: str) -> tuple[str, str]:
    """从 DB orders_pool 取出一条订单（pop 首行），返回 (email, order_id)。"""
    from web.database import get_session_factory
    from web.models import MailProvider

    factory = get_session_factory()
    async with factory() as session:
        row = await session.get(MailProvider, provider_id)
        if not row or not row.orders_pool:
            raise RuntimeError(f"[onlinemail] orders_pool 为空，请在管理界面添加订单")

        lines = [l.strip() for l in row.orders_pool.splitlines() if l.strip()]
        # 找第一条未使用订单（格式: email----orderId）
        if not lines:
            raise RuntimeError("[onlinemail] orders_pool 已耗尽，请补充订单")

        first = lines[0]
        remaining = lines[1:]
        row.orders_pool = "\n".join(remaining)
        await session.commit()

    if "----" not in first:
        raise RuntimeError(f"[onlinemail] 订单格式错误（应为 email----orderId）: {first}")
    email, order_id = first.split("----", 1)
    return email.strip(), order_id.strip()


# ─── Provider 构建 ────────────────────────────────────────────────────────────

def _build_provider(row: dict):
    """根据 DB 行构建 mail provider 实例。"""
    ptype = row["provider_type"]
    cfg = json.loads(row["config_json"] or "{}")
    pid = row["id"]

    if ptype == "onlinemail":
        with _instance_lock:
            if pid not in _onlinemail_instances:
                # onlinemail 的 orders 由 DB pop 管理，_file_pop 不再使用
                # 传入空 orders_file，mode 固定为 "api" 但实际 create_mailbox 由工厂接管
                _onlinemail_instances[pid] = OnlineMailProvider(
                    api_url="https://api.online-disposablemail.com/api",
                    api_key=cfg.get("api_key", ""),
                    orders_file="",          # 不再使用文件
                    mode=cfg.get("mode", "api"),
                )
            return _onlinemail_instances[pid]

    if ptype == "duckmail":
        return DuckMailProvider(
            api_url=cfg.get("api_url", "https://api.duckmail.sbs"),
            api_key=cfg.get("api_key", ""),
            domains=cfg.get("domains", []),
        )

    # default: cloudflare
    domain = _SELECTED_DOMAIN or cfg.get("domain", "")
    return CloudflareProvider(
        api_url=cfg.get("api_url", ""),
        api_token=cfg.get("api_token", ""),
        domain=domain,
    )


# ─── 公开接口 ─────────────────────────────────────────────────────────────────

def get_provider():
    """返回当前激活的 mail provider 实例（同步，可在注册线程中调用）。"""
    row = _run_async(_load_active_provider_row())
    if row is None:
        raise RuntimeError(
            "未配置邮件服务商，请在 Web 管理界面 → 邮件服务商 中添加并启用一个服务商"
        )
    return _build_provider(row)


def _rand_str(n=8):
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def _normalize_service(service):
    service = (service or "tavily").strip().lower()
    return service if service in _SUPPORTED_SERVICES else "tavily"


def _username_prefix(service):
    prefixes = {
        "firecrawl": "fc",
        "exa": "exa",
        "you": "you",
        "serper": "serper",
        "valyu": "valyu",
    }
    return prefixes.get(_normalize_service(service), "tavily")


def create_email(service: str = "tavily") -> tuple[str, str]:
    """
    创建临时邮箱，返回 (email, password)。
    对 onlinemail provider：直接从 DB orders_pool 弹出订单，不走 provider.create_mailbox。
    """
    row = _run_async(_load_active_provider_row())
    if row is None:
        raise RuntimeError(
            "未配置邮件服务商，请在 Web 管理界面 → 邮件服务商 中添加并启用一个服务商"
        )

    ptype = row["provider_type"]
    pid = row["id"]

    if ptype == "onlinemail":
        email, order_id = _run_async(_pop_onlinemail_order(pid, service))
        # 注册 onlinemail provider 的 mailbox_cache（供后续 get_messages 使用）
        provider = _build_provider(row)
        provider._mailbox_cache[email] = {"order_id": order_id}
        print(f"✅ 邮箱(onlinemail): {email}")
        return email, ""

    password = f"Tv{_rand_str(6)}{random.randint(100, 999)}!A"
    prefix = _username_prefix(service)
    provider = _build_provider(row)
    email, pw = provider.create_mailbox(prefix)
    if pw:
        password = pw
    print(f"✅ 邮箱({ptype}): {email}")
    return email, password
