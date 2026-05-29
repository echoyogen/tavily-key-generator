from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from web.auth import get_current_user
from web.database import get_db
from web.models import MailOrder
from web.schemas import MailOrderBulkCreate, MailOrderOut

router = APIRouter(prefix="/api/mail-orders", tags=["mail"])


@router.get("", response_model=dict)
async def list_orders(
    used: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    q = select(MailOrder)
    count_q = select(func.count(MailOrder.id))
    if used is not None:
        q = q.where(MailOrder.used == used)
        count_q = count_q.where(MailOrder.used == used)

    total = (await db.execute(count_q)).scalar_one()
    offset = (page - 1) * page_size
    items = (await db.execute(
        q.order_by(MailOrder.created_at.desc()).offset(offset).limit(page_size)
    )).scalars().all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [MailOrderOut.model_validate(o) for o in items],
    }


@router.post("", status_code=201)
async def bulk_create_orders(
    req: MailOrderBulkCreate,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    """批量添加邮箱订单，每行格式：email----orderId"""
    lines = req.lines.strip().splitlines()
    inserted = 0
    skipped = 0

    for line in lines:
        line = line.strip()
        if not line or "----" not in line:
            continue
        parts = line.split("----", 1)
        if len(parts) != 2:
            continue
        email, order_id = parts[0].strip(), parts[1].strip()
        if not email or not order_id:
            continue

        # 检查重复
        exists = (await db.execute(
            select(MailOrder).where(
                MailOrder.email == email, MailOrder.order_id == order_id
            )
        )).scalar_one_or_none()

        if exists:
            skipped += 1
            continue

        db.add(MailOrder(email=email, order_id=order_id, used=False))
        inserted += 1

    await db.commit()
    return {"inserted": inserted, "skipped": skipped}


@router.delete("/{order_id}", status_code=204)
async def delete_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    order = await db.get(MailOrder, order_id)
    if order is None:
        raise HTTPException(404, "订单不存在")
    await db.delete(order)
    await db.commit()


@router.delete("", status_code=204)
async def bulk_delete_orders(
    ids: List[int] = Query(...),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    await db.execute(delete(MailOrder).where(MailOrder.id.in_(ids)))
    await db.commit()
