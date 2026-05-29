"""
APScheduler 定时任务管理。
每个 Schedule 记录对应一个 APScheduler CronTrigger job。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_scheduler: Optional[object] = None  # AsyncIOScheduler 实例
_loop: Optional[asyncio.AbstractEventLoop] = None


def init_scheduler(loop: asyncio.AbstractEventLoop):
    global _scheduler, _loop
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    _loop = loop
    _scheduler = AsyncIOScheduler(timezone="UTC")
    _scheduler.start()
    logger.info("[scheduler] APScheduler 已启动")


def shutdown_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("[scheduler] APScheduler 已停止")


async def load_all_schedules():
    """启动时从 DB 加载所有启用的定时任务。"""
    from web.database import get_session_factory
    from web.models import Schedule
    from sqlalchemy import select

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(select(Schedule).where(Schedule.enabled == True))
        schedules = result.scalars().all()

    for s in schedules:
        _add_job(s.id, s.service, s.cron_expr, s.count, s.concurrency, s.delay, s.upload)

    logger.info(f"[scheduler] 已加载 {len(schedules)} 个定时任务")


def _add_job(schedule_id: int, service: str, cron_expr: str,
             count: int, concurrency: int, delay: int, upload: bool):
    """向 APScheduler 添加一个 cron job。"""
    if _scheduler is None:
        return

    job_id = f"schedule_{schedule_id}"
    # 移除旧 job（如果存在）
    if _scheduler.get_job(job_id):
        _scheduler.remove_job(job_id)

    parts = cron_expr.strip().split()
    if len(parts) != 5:
        logger.warning(f"[scheduler] 无效 cron 表达式: {cron_expr}")
        return

    minute, hour, day, month, day_of_week = parts
    from apscheduler.triggers.cron import CronTrigger

    _scheduler.add_job(
        _run_scheduled_task,
        CronTrigger(
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
            timezone="UTC",
        ),
        id=job_id,
        kwargs={
            "schedule_id": schedule_id,
            "service": service,
            "count": count,
            "concurrency": concurrency,
            "delay": delay,
            "upload": upload,
        },
        replace_existing=True,
    )
    logger.info(f"[scheduler] job {job_id} 已注册: {service} @ {cron_expr}")


async def _run_scheduled_task(
    schedule_id: int, service: str, count: int,
    concurrency: int, delay: int, upload: bool,
):
    """定时触发：在 DB 创建 Task 记录，然后提交到 worker。"""
    from web.database import get_session_factory
    from web.models import Task, Schedule
    from web.worker import submit_task

    factory = get_session_factory()
    async with factory() as session:
        task = Task(
            service=service,
            total=count,
            concurrency=concurrency,
            delay=delay,
            upload=upload,
            status="pending",
        )
        session.add(task)
        await session.flush()
        task_id = task.id

        # 更新最后运行时间
        sched = await session.get(Schedule, schedule_id)
        if sched:
            sched.last_run_at = datetime.now(timezone.utc)
            # 更新 next_run_at
            job = _scheduler.get_job(f"schedule_{schedule_id}") if _scheduler else None
            if job and job.next_run_time:
                sched.next_run_at = job.next_run_time

        await session.commit()

    loop = asyncio.get_event_loop()
    submit_task(task_id, service, count, concurrency, delay, upload, loop)
    logger.info(f"[scheduler] 定时任务触发: task_id={task_id}, service={service}")


async def add_schedule(schedule_id: int, service: str, cron_expr: str,
                       count: int, concurrency: int, delay: int, upload: bool):
    """添加或更新定时任务（同时更新 APScheduler 和 DB next_run_at）。"""
    _add_job(schedule_id, service, cron_expr, count, concurrency, delay, upload)
    await _refresh_next_run(schedule_id)


async def remove_schedule(schedule_id: int):
    if _scheduler is None:
        return
    job_id = f"schedule_{schedule_id}"
    if _scheduler.get_job(job_id):
        _scheduler.remove_job(job_id)


async def _refresh_next_run(schedule_id: int):
    if _scheduler is None:
        return
    job = _scheduler.get_job(f"schedule_{schedule_id}")
    if not job:
        return
    next_run = job.next_run_time
    from web.database import get_session_factory
    from web.models import Schedule
    factory = get_session_factory()
    async with factory() as session:
        sched = await session.get(Schedule, schedule_id)
        if sched:
            sched.next_run_at = next_run
            await session.commit()
