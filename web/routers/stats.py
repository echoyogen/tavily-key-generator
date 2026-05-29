from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from web.auth import get_current_user
from web.database import get_db
from web.models import Account, Task
from web.schemas import ServiceStats, StatsResponse

router = APIRouter(prefix="/api", tags=["stats"])

_SERVICES = ["tavily", "firecrawl", "exa", "you", "serper", "valyu"]


@router.get("/stats", response_model=StatsResponse)
async def get_stats(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    services_stats = []
    total_accounts = 0
    total_valid = 0

    for svc in _SERVICES:
        # 各状态计数
        counts = (await db.execute(
            select(Account.is_valid, func.count(Account.id))
            .where(Account.service == svc)
            .group_by(Account.is_valid)
        )).all()

        valid = invalid = unverified = 0
        for is_valid, cnt in counts:
            if is_valid == 1:
                valid = cnt
            elif is_valid == 0:
                invalid = cnt
            else:
                unverified = cnt

        # 今日新增
        today_new = (await db.execute(
            select(func.count(Account.id)).where(
                Account.service == svc,
                Account.created_at >= today_start,
            )
        )).scalar_one()

        total = valid + invalid + unverified
        total_accounts += total
        total_valid += valid

        services_stats.append(ServiceStats(
            service=svc,
            total=total,
            valid=valid,
            invalid=invalid,
            unverified=unverified,
            today_new=today_new,
        ))

    # 任务统计
    pending_tasks = (await db.execute(
        select(func.count(Task.id)).where(Task.status == "pending")
    )).scalar_one()
    running_tasks = (await db.execute(
        select(func.count(Task.id)).where(Task.status == "running")
    )).scalar_one()

    return StatsResponse(
        services=services_stats,
        total_accounts=total_accounts,
        total_valid=total_valid,
        pending_tasks=pending_tasks,
        running_tasks=running_tasks,
    )
