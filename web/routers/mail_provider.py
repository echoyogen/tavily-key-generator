"""
邮件服务商管理 Router。

提供：
  GET    /api/mail-providers              列出所有服务商
  POST   /api/mail-providers              创建服务商
  GET    /api/mail-providers/{id}         获取单个服务商
  PATCH  /api/mail-providers/{id}         更新服务商
  DELETE /api/mail-providers/{id}         删除服务商
  POST   /api/mail-providers/{id}/orders  批量追加 onlinemail 订单到 orders_pool
  DELETE /api/mail-providers/{id}/orders  清空 orders_pool

  GET    /api/mail-providers/usages       分页查询 EmailUsage（跨所有服务商）
  GET    /api/mail-providers/{id}/usages  分页查询单个服务商的 EmailUsage
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from web.auth import get_current_user
from web.database import get_db
from web.models import EmailUsage, MailProvider
from web.schemas import (
    EmailUsageListResponse,
    EmailUsageOut,
    MailProviderAddOrders,
    MailProviderCreate,
    MailProviderOut,
    MailProviderUpdate,
)

router = APIRouter(prefix="/api/mail-providers", tags=["mail-providers"])


# ─── 辅助 ─────────────────────────────────────────────────────────────────────

def _to_out(row: MailProvider) -> MailProviderOut:
    pool = row.orders_pool or ""
    remaining = len([l for l in pool.splitlines() if l.strip()])
    return MailProviderOut(
        id=row.id,
        provider_type=row.provider_type,
        name=row.name,
        config_json=row.config_json,
        enabled=row.enabled,
        orders_remaining=remaining,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# ─── 服务商 CRUD ──────────────────────────────────────────────────────────────

@router.get("", response_model=List[MailProviderOut])
async def list_providers(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    rows = (await db.execute(select(MailProvider).order_by(MailProvider.id))).scalars().all()
    return [_to_out(r) for r in rows]


@router.post("", response_model=MailProviderOut, status_code=201)
async def create_provider(
    req: MailProviderCreate,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    if req.provider_type not in ("cloudflare", "duckmail", "onlinemail"):
        raise HTTPException(400, "provider_type 必须是 cloudflare / duckmail / onlinemail")

    row = MailProvider(
        provider_type=req.provider_type,
        name=req.name,
        config_json=req.config_json,
        enabled=req.enabled,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _to_out(row)


@router.get("/usages", response_model=EmailUsageListResponse)
async def list_all_usages(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    target_service: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    """跨所有服务商查询邮箱使用记录。"""
    return await _query_usages(db, None, page, page_size, target_service, status)


@router.get("/{provider_id}", response_model=MailProviderOut)
async def get_provider(
    provider_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    row = await db.get(MailProvider, provider_id)
    if not row:
        raise HTTPException(404, "服务商不存在")
    return _to_out(row)


@router.patch("/{provider_id}", response_model=MailProviderOut)
async def update_provider(
    provider_id: int,
    req: MailProviderUpdate,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    row = await db.get(MailProvider, provider_id)
    if not row:
        raise HTTPException(404, "服务商不存在")

    if req.name is not None:
        row.name = req.name
    if req.config_json is not None:
        row.config_json = req.config_json
    if req.enabled is not None:
        row.enabled = req.enabled
        if req.enabled:
            # 启用时禁用其他（同一时间只有一个激活 provider）
            others = (await db.execute(
                select(MailProvider).where(MailProvider.id != provider_id)
            )).scalars().all()
            for o in others:
                o.enabled = False

    await db.commit()
    await db.refresh(row)
    return _to_out(row)


@router.delete("/{provider_id}", status_code=204)
async def delete_provider(
    provider_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    row = await db.get(MailProvider, provider_id)
    if not row:
        raise HTTPException(404, "服务商不存在")
    await db.delete(row)
    await db.commit()


# ─── orders_pool 管理（onlinemail 专用）──────────────────────────────────────

@router.post("/{provider_id}/orders", response_model=MailProviderOut)
async def add_orders(
    provider_id: int,
    req: MailProviderAddOrders,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    """追加 onlinemail 订单到 orders_pool（不去重）。"""
    row = await db.get(MailProvider, provider_id)
    if not row:
        raise HTTPException(404, "服务商不存在")
    if row.provider_type != "onlinemail":
        raise HTTPException(400, "只有 onlinemail 类型服务商支持订单池")

    new_lines = [l.strip() for l in req.lines.splitlines() if l.strip() and "----" in l]
    if not new_lines:
        raise HTTPException(400, "未找到有效订单行，格式应为 email----orderId")

    existing = row.orders_pool or ""
    merged = (existing.rstrip("\n") + "\n" + "\n".join(new_lines)).lstrip("\n")
    row.orders_pool = merged
    await db.commit()
    await db.refresh(row)
    return _to_out(row)


@router.delete("/{provider_id}/orders", status_code=204)
async def clear_orders(
    provider_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    """清空 orders_pool。"""
    row = await db.get(MailProvider, provider_id)
    if not row:
        raise HTTPException(404, "服务商不存在")
    row.orders_pool = None
    await db.commit()


# ─── EmailUsage 查询 ──────────────────────────────────────────────────────────

@router.get("/{provider_id}/usages", response_model=EmailUsageListResponse)
async def list_provider_usages(
    provider_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    target_service: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    row = await db.get(MailProvider, provider_id)
    if not row:
        raise HTTPException(404, "服务商不存在")
    return await _query_usages(db, provider_id, page, page_size, target_service, status)


async def _query_usages(
    db: AsyncSession,
    provider_id: Optional[int],
    page: int,
    page_size: int,
    target_service: Optional[str],
    status: Optional[str],
) -> EmailUsageListResponse:
    base = select(EmailUsage)
    count_base = select(func.count()).select_from(EmailUsage)

    if provider_id is not None:
        base = base.where(EmailUsage.provider_id == provider_id)
        count_base = count_base.where(EmailUsage.provider_id == provider_id)
    if target_service:
        base = base.where(EmailUsage.target_service == target_service)
        count_base = count_base.where(EmailUsage.target_service == target_service)
    if status:
        base = base.where(EmailUsage.status == status)
        count_base = count_base.where(EmailUsage.status == status)

    total = (await db.execute(count_base)).scalar_one()
    rows = (await db.execute(
        base.order_by(EmailUsage.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
    )).scalars().all()

    # 批量查 provider name
    provider_ids = {r.provider_id for r in rows}
    providers = {}
    if provider_ids:
        prows = (await db.execute(
            select(MailProvider).where(MailProvider.id.in_(provider_ids))
        )).scalars().all()
        providers = {p.id: p.name for p in prows}

    items = [
        EmailUsageOut(
            id=r.id,
            provider_id=r.provider_id,
            provider_name=providers.get(r.provider_id),
            task_id=r.task_id,
            email=r.email,
            order_id=r.order_id,
            target_service=r.target_service,
            status=r.status,
            api_key=r.api_key,
            fail_reason=r.fail_reason,
            created_at=r.created_at,
            finished_at=r.finished_at,
        )
        for r in rows
    ]
    return EmailUsageListResponse(total=total, page=page, page_size=page_size, items=items)
