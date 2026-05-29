import csv
import io
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from web.auth import get_current_user
from web.database import get_db
from web.models import Account
from web.schemas import AccountListResponse, AccountOut

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


@router.get("", response_model=AccountListResponse)
async def list_accounts(
    service: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    is_valid: Optional[int] = Query(None, description="0=失效 1=有效 2=未验证"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    q = select(Account)
    count_q = select(func.count(Account.id))

    if service:
        q = q.where(Account.service == service)
        count_q = count_q.where(Account.service == service)
    if is_valid is not None:
        q = q.where(Account.is_valid == is_valid)
        count_q = count_q.where(Account.is_valid == is_valid)
    if keyword:
        like = f"%{keyword}%"
        q = q.where(
            Account.email.like(like) | Account.api_key.like(like)
        )
        count_q = count_q.where(
            Account.email.like(like) | Account.api_key.like(like)
        )

    total = (await db.execute(count_q)).scalar_one()
    offset = (page - 1) * page_size
    items = (await db.execute(
        q.order_by(Account.created_at.desc()).offset(offset).limit(page_size)
    )).scalars().all()

    return AccountListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[AccountOut.model_validate(a) for a in items],
    )


@router.delete("/{account_id}", status_code=204)
async def delete_account(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    result = await db.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    await db.delete(account)
    await db.commit()


@router.delete("", status_code=204)
async def bulk_delete_accounts(
    ids: List[int] = Query(..., description="要删除的账号 ID 列表"),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    await db.execute(delete(Account).where(Account.id.in_(ids)))
    await db.commit()


@router.get("/export/csv")
async def export_csv(
    service: Optional[str] = Query(None),
    is_valid: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    q = select(Account)
    if service:
        q = q.where(Account.service == service)
    if is_valid is not None:
        q = q.where(Account.is_valid == is_valid)
    items = (await db.execute(q.order_by(Account.created_at.desc()))).scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "service", "email", "password", "api_key",
                     "is_valid", "last_verified_at", "created_at", "uploaded"])
    for a in items:
        writer.writerow([
            a.id, a.service, a.email, a.password or "", a.api_key,
            a.is_valid,
            a.last_verified_at.isoformat() if a.last_verified_at else "",
            a.created_at.isoformat(),
            a.uploaded,
        ])

    output.seek(0)
    filename = f"accounts_{service or 'all'}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
