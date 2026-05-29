from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from web.auth import get_current_user
from web.database import get_db
from web.models import Schedule
from web.schemas import ScheduleCreateRequest, ScheduleOut, ScheduleUpdateRequest

router = APIRouter(prefix="/api/schedule", tags=["schedule"])

_VALID_SERVICES = {"tavily", "firecrawl", "exa", "you", "serper", "valyu"}


@router.get("", response_model=List[ScheduleOut])
async def list_schedules(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    items = (await db.execute(
        select(Schedule).order_by(Schedule.created_at.desc())
    )).scalars().all()
    return [ScheduleOut.model_validate(s) for s in items]


@router.post("", response_model=ScheduleOut, status_code=201)
async def create_schedule(
    req: ScheduleCreateRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    if req.service not in _VALID_SERVICES:
        raise HTTPException(400, f"不支持的服务: {req.service}")

    parts = req.cron_expr.strip().split()
    if len(parts) != 5:
        raise HTTPException(400, "cron_expr 必须是标准 5 段格式，如 '0 2 * * *'")

    sched = Schedule(
        service=req.service,
        cron_expr=req.cron_expr.strip(),
        count=req.count,
        concurrency=req.concurrency,
        delay=req.delay,
        upload=req.upload,
        enabled=req.enabled,
    )
    db.add(sched)
    await db.commit()
    await db.refresh(sched)

    if req.enabled:
        from web.scheduler import add_schedule
        await add_schedule(
            sched.id, sched.service, sched.cron_expr,
            sched.count, sched.concurrency, sched.delay, sched.upload,
        )

    return ScheduleOut.model_validate(sched)


@router.put("/{schedule_id}", response_model=ScheduleOut)
async def update_schedule(
    schedule_id: int,
    req: ScheduleUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    sched = await db.get(Schedule, schedule_id)
    if sched is None:
        raise HTTPException(404, "定时任务不存在")

    if req.cron_expr is not None:
        parts = req.cron_expr.strip().split()
        if len(parts) != 5:
            raise HTTPException(400, "cron_expr 必须是标准 5 段格式")
        sched.cron_expr = req.cron_expr.strip()
    if req.count is not None:
        sched.count = req.count
    if req.concurrency is not None:
        sched.concurrency = req.concurrency
    if req.delay is not None:
        sched.delay = req.delay
    if req.upload is not None:
        sched.upload = req.upload
    if req.enabled is not None:
        sched.enabled = req.enabled

    await db.commit()
    await db.refresh(sched)

    from web.scheduler import add_schedule, remove_schedule
    if sched.enabled:
        await add_schedule(
            sched.id, sched.service, sched.cron_expr,
            sched.count, sched.concurrency, sched.delay, sched.upload,
        )
    else:
        await remove_schedule(sched.id)

    return ScheduleOut.model_validate(sched)


@router.delete("/{schedule_id}", status_code=204)
async def delete_schedule(
    schedule_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    sched = await db.get(Schedule, schedule_id)
    if sched is None:
        raise HTTPException(404, "定时任务不存在")

    from web.scheduler import remove_schedule
    await remove_schedule(schedule_id)

    await db.delete(sched)
    await db.commit()
