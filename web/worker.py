"""
注册任务后台执行器。
- 使用全局 ThreadPoolExecutor 异步运行注册逻辑
- 通过 contextvar 在线程中绑定 task_id
- 拦截线程范围内的 print/stdout 输出，写入 task_logs 表
- 注册成功的账号同时写入 accounts 表
"""
from __future__ import annotations

import asyncio
import io
import logging
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logger = logging.getLogger(__name__)

# 全局线程池（最大 20 个并发注册线程）
_executor = ThreadPoolExecutor(max_workers=20, thread_name_prefix="reg-worker")

# 当前线程绑定的 task_id（通过 threading.local 实现线程隔离）
_thread_local = threading.local()

# 运行中任务的取消标志 {task_id: threading.Event}
_cancel_flags: dict[int, threading.Event] = {}
_cancel_lock = threading.Lock()


def request_cancel(task_id: int):
    with _cancel_lock:
        flag = _cancel_flags.get(task_id)
    if flag:
        flag.set()


def is_cancelled(task_id: int) -> bool:
    with _cancel_lock:
        flag = _cancel_flags.get(task_id)
    return flag.is_set() if flag else False


# ─── stdout 拦截器 ────────────────────────────────────────────────────────────

class _TaskLogWriter(io.TextIOBase):
    """将 write() 调用路由到数据库日志写入队列。"""

    def __init__(self, task_id: int, loop: asyncio.AbstractEventLoop, level: str = "info"):
        self._task_id = task_id
        self._loop = loop
        self._level = level
        self._buf = ""

    def write(self, s: str) -> int:
        self._buf += s
        # 按行分割，每完整行提交一次
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            line = line.strip()
            if line:
                self._emit(line)
        return len(s)

    def flush(self):
        if self._buf.strip():
            self._emit(self._buf.strip())
            self._buf = ""

    def _emit(self, message: str):
        level = self._level
        msg_lower = message.lower()
        if any(w in msg_lower for w in ("error", "❌", "失败", "exception")):
            level = "error"
        elif any(w in msg_lower for w in ("warning", "warn", "⚠")):
            level = "warning"
        elif any(w in msg_lower for w in ("✅", "成功", "success", "passed")):
            level = "success"

        # 线程安全地将日志写入 DB（通过 event loop 调度）
        asyncio.run_coroutine_threadsafe(
            _write_log(self._task_id, level, message),
            self._loop,
        )


@contextmanager
def _capture_stdout(task_id: int, loop: asyncio.AbstractEventLoop):
    """在当前线程范围内将 stdout 替换为 TaskLogWriter。"""
    writer = _TaskLogWriter(task_id, loop)
    old_stdout = sys.stdout
    # 只替换当前线程的输出（通过 threading.local 无法直接拦截全局 sys.stdout，
    # 这里用简单全局替换；注册是串行的单线程子流程，并发任务用不同 task 隔离）
    sys.stdout = writer
    try:
        yield writer
    finally:
        writer.flush()
        sys.stdout = old_stdout


# ─── DB 异步写入辅助 ─────────────────────────────────────────────────────────

async def _write_log(task_id: int, level: str, message: str):
    from web.database import get_session_factory
    from web.models import TaskLog
    factory = get_session_factory()
    async with factory() as session:
        session.add(TaskLog(task_id=task_id, level=level, message=message))
        await session.commit()


async def _update_task(task_id: int, **kwargs):
    from web.database import get_session_factory
    from web.models import Task
    factory = get_session_factory()
    async with factory() as session:
        task = await session.get(Task, task_id)
        if task:
            for k, v in kwargs.items():
                setattr(task, k, v)
            await session.commit()


async def _create_email_usage(
    task_id: int, service: str
) -> int:
    """预创建 EmailUsage 记录（pending），返回 usage_id。"""
    from web.database import get_session_factory
    from web.models import EmailUsage, MailProvider
    from sqlalchemy import select

    factory = get_session_factory()
    async with factory() as session:
        # 找当前激活的 provider id
        row = (await session.execute(
            select(MailProvider).where(MailProvider.enabled == True).limit(1)
        )).scalar_one_or_none()
        provider_id = row.id if row else 0

        usage = EmailUsage(
            provider_id=provider_id,
            task_id=task_id,
            email="",          # 尚未分配，注册后回填
            target_service=service,
            status="pending",
        )
        session.add(usage)
        await session.commit()
        await session.refresh(usage)
        return usage.id


async def _update_email_usage(
    usage_id: int,
    email: str = "",
    order_id: Optional[str] = None,
    status: str = "pending",
    api_key: Optional[str] = None,
    fail_reason: Optional[str] = None,
):
    from web.database import get_session_factory
    from web.models import EmailUsage
    from datetime import datetime, timezone

    factory = get_session_factory()
    async with factory() as session:
        usage = await session.get(EmailUsage, usage_id)
        if not usage:
            return
        if email:
            usage.email = email
        if order_id is not None:
            usage.order_id = order_id
        usage.status = status
        if api_key is not None:
            usage.api_key = api_key
        if fail_reason is not None:
            usage.fail_reason = fail_reason[:500]
        if status in ("success", "failed", "cancelled"):
            usage.finished_at = datetime.now(timezone.utc)
        await session.commit()


async def _save_account(service: str, email: str, password: Optional[str], api_key: str):
    from web.database import get_session_factory
    from web.models import Account
    from sqlalchemy import select
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(Account).where(Account.service == service, Account.api_key == api_key)
        )
        if result.scalar_one_or_none() is None:
            session.add(Account(
                service=service,
                email=email,
                password=password or None,
                api_key=api_key,
                is_valid=1,
                uploaded=False,
            ))
            await session.commit()


# ─── 注册单个账号（在线程中运行）────────────────────────────────────────────

def _register_one_sync(
    task_id: int,
    index: int,
    total: int,
    service: str,
    upload: bool,
    loop: asyncio.AbstractEventLoop,
) -> str:
    """在工作线程中执行单次注册，返回 'success' / 'success_no_key' / 'failed'。"""
    if is_cancelled(task_id):
        return "cancelled"

    print(f"{'='*50}")
    print(f"[{index}/{total}] 开始注册 {service}")
    print(f"{'='*50}")

    # 预创建 EmailUsage 追踪记录（status=pending，后续更新）
    usage_id: int = asyncio.run_coroutine_threadsafe(
        _create_email_usage(task_id, service), loop
    ).result(timeout=10)

    email = ""
    try:
        from mail.factory import create_email
        from services.registry import get_service
        from config import SERVER_URL, SERVER_ADMIN_PASSWORD
        import requests as std_requests

        email, password = create_email(service=service)

        # 回填邮箱地址（onlinemail 还需记录 order_id）
        order_id: Optional[str] = None
        try:
            from mail import factory as _mf
            row = asyncio.run_coroutine_threadsafe(
                _mf._load_active_provider_row(), loop
            ).result(timeout=5)
            if row and row["provider_type"] == "onlinemail":
                inst = _mf._onlinemail_instances.get(row["id"])
                if inst:
                    cache = inst._mailbox_cache.get(email, {})
                    order_id = cache.get("order_id")
        except Exception:
            pass

        asyncio.run_coroutine_threadsafe(
            _update_email_usage(usage_id, email=email, order_id=order_id, status="pending"),
            loop,
        )

        svc = get_service(service)
        api_key = svc.register(email, password)

        if api_key and api_key != "SUCCESS_NO_KEY":
            print(f"✅ 注册成功: {email} -> {api_key[:20]}...")
            # 写入账号 DB
            asyncio.run_coroutine_threadsafe(
                _save_account(service, email, password, api_key), loop
            ).result(timeout=10)
            # 更新邮箱使用记录
            asyncio.run_coroutine_threadsafe(
                _update_email_usage(usage_id, status="success", api_key=api_key), loop
            )

            if upload and SERVER_URL:
                try:
                    r = std_requests.post(
                        f"{SERVER_URL}/api/keys",
                        json={"key": api_key, "email": email, "service": service},
                        headers={"Authorization": f"Bearer {SERVER_ADMIN_PASSWORD}"},
                        timeout=15,
                    )
                    if r.status_code in (200, 201):
                        print("✅ 已上传到服务器")
                        asyncio.run_coroutine_threadsafe(
                            _mark_uploaded(service, api_key), loop
                        )
                    else:
                        print(f"⚠️ 上传失败: {r.status_code}")
                except Exception as ue:
                    print(f"⚠️ 上传异常: {ue}")

            return "success"

        if api_key == "SUCCESS_NO_KEY":
            print(f"✅ 注册成功（无 Key）: {email}")
            asyncio.run_coroutine_threadsafe(
                _update_email_usage(usage_id, status="success"), loop
            )
            return "success_no_key"

        print("❌ 注册失败：未获取到 API Key")
        asyncio.run_coroutine_threadsafe(
            _update_email_usage(usage_id, status="failed",
                                fail_reason="未获取到 API Key"), loop
        )
        return "failed"

    except Exception as e:
        print(f"❌ 注册异常: {e}")
        asyncio.run_coroutine_threadsafe(
            _update_email_usage(usage_id, email=email, status="failed",
                                fail_reason=str(e)[:500]), loop
        )
        return "failed"


async def _mark_uploaded(service: str, api_key: str):
    from web.database import get_session_factory
    from web.models import Account
    from sqlalchemy import select
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(Account).where(Account.service == service, Account.api_key == api_key)
        )
        acc = result.scalar_one_or_none()
        if acc:
            acc.uploaded = True
            await session.commit()


# ─── 任务主流程（在线程池中运行）────────────────────────────────────────────

def _run_task_sync(task_id: int, service: str, total: int, concurrency: int, delay: int,
                   upload: bool, loop: asyncio.AbstractEventLoop):
    """任务主线程：协调并发注册子线程。"""
    import time
    from concurrent.futures import ThreadPoolExecutor as TPE, wait, FIRST_COMPLETED

    # 注册取消标志
    cancel_event = threading.Event()
    with _cancel_lock:
        _cancel_flags[task_id] = cancel_event

    asyncio.run_coroutine_threadsafe(
        _update_task(task_id, status="running"), loop
    ).result(timeout=5)
    asyncio.run_coroutine_threadsafe(
        _write_log(task_id, "info", f"任务开始：{service} x{total}，并发={concurrency}，间隔={delay}s"), loop
    ).result(timeout=5)

    success = failed = 0
    actual_concurrency = max(1, min(concurrency, total))

    with _capture_stdout(task_id, loop):
        with TPE(max_workers=actual_concurrency, thread_name_prefix=f"task{task_id}") as inner:
            futures = {}
            next_index = 1

            # 初始填满并发槽
            while next_index <= total and len(futures) < actual_concurrency:
                if cancel_event.is_set():
                    break
                f = inner.submit(
                    _register_one_sync, task_id, next_index, total, service, upload, loop
                )
                futures[f] = next_index
                next_index += 1

            while futures:
                if cancel_event.is_set():
                    break
                done, _ = wait(list(futures.keys()), return_when=FIRST_COMPLETED)
                for f in done:
                    futures.pop(f, None)
                    try:
                        status = f.result()
                    except Exception as e:
                        status = "failed"
                        asyncio.run_coroutine_threadsafe(
                            _write_log(task_id, "error", f"子线程异常: {e}"), loop
                        )

                    if status in ("success", "success_no_key"):
                        success += 1
                    elif status == "cancelled":
                        pass
                    else:
                        failed += 1

                    asyncio.run_coroutine_threadsafe(
                        _update_task(task_id, success=success, failed=failed), loop
                    )

                    # 补充新任务
                    if next_index <= total and not cancel_event.is_set():
                        if delay > 0:
                            time.sleep(delay)
                        nf = inner.submit(
                            _register_one_sync, task_id, next_index, total, service, upload, loop
                        )
                        futures[nf] = next_index
                        next_index += 1

    # 最终状态
    final_status = "cancelled" if cancel_event.is_set() else "done"
    asyncio.run_coroutine_threadsafe(
        _update_task(
            task_id,
            status=final_status,
            success=success,
            failed=failed,
            finished_at=datetime.now(timezone.utc),
        ), loop
    ).result(timeout=5)
    asyncio.run_coroutine_threadsafe(
        _write_log(task_id, "info",
                   f"任务{final_status}：成功 {success}，失败 {failed}"), loop
    )

    with _cancel_lock:
        _cancel_flags.pop(task_id, None)


# ─── 公开接口 ────────────────────────────────────────────────────────────────

def submit_task(task_id: int, service: str, total: int, concurrency: int, delay: int,
                upload: bool, loop: asyncio.AbstractEventLoop):
    """将注册任务提交到全局线程池。非阻塞，立即返回。"""
    _executor.submit(
        _run_task_sync, task_id, service, total, concurrency, delay, upload, loop
    )
