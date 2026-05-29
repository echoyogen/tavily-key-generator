import asyncio
import json
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from web.auth import get_current_user
from web.database import get_db
from web.models import Task, TaskLog
from web.schemas import TaskCreateRequest, TaskOut
from web.worker import submit_task, request_cancel

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

_VALID_SERVICES = {"tavily", "firecrawl", "exa", "you", "serper", "valyu"}


@router.post("", response_model=TaskOut, status_code=201)
async def create_task(
    req: TaskCreateRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    if req.service not in _VALID_SERVICES:
        raise HTTPException(400, f"不支持的服务: {req.service}，可选: {sorted(_VALID_SERVICES)}")

    task = Task(
        service=req.service,
        total=req.count,
        concurrency=req.concurrency,
        delay=req.delay,
        upload=req.upload,
        status="pending",
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    loop = asyncio.get_event_loop()
    submit_task(task.id, req.service, req.count, req.concurrency, req.delay, req.upload, loop)

    return TaskOut.model_validate(task)


@router.get("", response_model=list[TaskOut])
async def list_tasks(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    items = (await db.execute(
        select(Task).order_by(Task.created_at.desc()).limit(limit)
    )).scalars().all()
    return [TaskOut.model_validate(t) for t in items]


@router.get("/{task_id}", response_model=TaskOut)
async def get_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")
    return TaskOut.model_validate(task)


@router.delete("/{task_id}", status_code=204)
async def cancel_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")
    if task.status not in ("pending", "running"):
        raise HTTPException(400, f"任务状态 '{task.status}' 无法取消")
    request_cancel(task_id)
    return


@router.get("/{task_id}/stream")
async def stream_task_logs(
    task_id: int,
    cursor: int = Query(0, description="上次收到的最大日志 ID，首次传 0"),
    token: str = Query(..., description="JWT token（SSE 无法携带 Authorization header）"),
):
    # SSE 通过 query param 传 token
    from web.auth import decode_token
    username = decode_token(token)
    if not username:
        raise HTTPException(401, "Token 无效")

    async def event_generator() -> AsyncGenerator[str, None]:
        from web.database import get_session_factory
        from web.models import Task as TaskModel, TaskLog as TaskLogModel

        factory = get_session_factory()
        last_id = cursor
        done_statuses = {"done", "cancelled", "failed"}

        while True:
            async with factory() as session:
                # 拉取新日志
                logs = (await session.execute(
                    select(TaskLogModel)
                    .where(
                        TaskLogModel.task_id == task_id,
                        TaskLogModel.id > last_id,
                    )
                    .order_by(TaskLogModel.id.asc())
                    .limit(50)
                )).scalars().all()

                for log in logs:
                    last_id = log.id
                    log_data = {
                        "id": log.id,
                        "level": log.level,
                        "message": log.message,
                        "created_at": log.created_at.isoformat(),
                    }
                    yield f"data: {json.dumps(log_data)}\n\n"

                # 检查任务是否已结束
                task = await session.get(TaskModel, task_id)
                if task and task.status in done_statuses:
                    # 推送剩余日志后发送结束事件
                    if not logs:
                        yield f"event: done\ndata: {task.status}\n\n"
                        return
                elif task is None:
                    yield f"event: done\ndata: not_found\n\n"
                    return

            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
