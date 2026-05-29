"""
Key 有效性验证 Router。
复用 services/common/api_verifier.py 中的 verify_api_key。
"""
import asyncio
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from web.auth import get_current_user
from web.database import get_db
from web.models import Account
from web.schemas import VerifyRequest, VerifyResult

router = APIRouter(prefix="/api/verify", tags=["verify"])

# 各平台验证配置
_VERIFY_CONFIGS = {
    "tavily": {
        "endpoint": "https://api.tavily.com/search",
        "headers": lambda k: {"Authorization": f"Bearer {k}", "Content-Type": "application/json"},
        "body": '{"query":"test","max_results":1}',
        "expected_status": 200,
    },
    "firecrawl": {
        "endpoint": "https://api.firecrawl.dev/v2/scrape",
        "headers": lambda k: {"Authorization": f"Bearer {k}", "Content-Type": "application/json"},
        "expected_status": 200,
    },
    "exa": {
        "endpoint": "https://api.exa.ai/search",
        "headers": lambda k: {"x-api-key": k, "Content-Type": "application/json"},
        "expected_status": 200,
    },
    "you": {
        "method": "GET",
        "endpoint": "https://api.you.com/v1/search",
        "params": {"query": "test", "num_web_results": 1},
        "headers": lambda k: {"X-API-Key": k, "Accept": "application/json"},
        "expected_status": 200,
    },
    "serper": {
        "endpoint": "https://google.serper.dev/search",
        "headers": lambda k: {"X-API-KEY": k, "Content-Type": "application/json"},
        "expected_status": 200,
    },
    "valyu": {
        "endpoint": "https://api.valyu.ai/v1/search",
        "headers": lambda k: {"x-api-key": k, "Content-Type": "application/json"},
        "expected_status": 200,
    },
}


def _do_verify(service: str, api_key: str) -> int:
    """同步验证单个 Key，返回 is_valid 值（0/1/2）。"""
    cfg = _VERIFY_CONFIGS.get(service)
    if cfg is None:
        return 2  # 未知平台，标记为未验证

    import requests
    method = cfg.get("method", "POST").upper()
    try:
        if method == "GET":
            resp = requests.get(
                cfg["endpoint"],
                headers=cfg["headers"](api_key),
                params=cfg.get("params"),
                timeout=20,
            )
        else:
            resp = requests.post(
                cfg["endpoint"],
                headers=cfg["headers"](api_key),
                json={"query": "test", "max_results": 1},
                timeout=20,
            )
        if resp.status_code == cfg.get("expected_status", 200):
            return 1
        if resp.status_code in (401, 403):
            return 0
        # 其他状态码（如 429 rate limit）保守标记为未验证
        return 2
    except Exception:
        return 2


@router.post("", response_model=List[VerifyResult])
async def verify_keys(
    req: VerifyRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
):
    # 确定要验证的账号列表
    if req.ids:
        accounts = (await db.execute(
            select(Account).where(Account.id.in_(req.ids))
        )).scalars().all()
    elif req.service:
        q = select(Account).where(Account.service == req.service)
        if not req.all:
            q = q.where(Account.is_valid != 1)  # 默认只验证非有效的
        accounts = (await db.execute(q)).scalars().all()
    else:
        raise HTTPException(400, "请提供 ids 或 service 参数")

    if not accounts:
        return []

    results = []
    loop = asyncio.get_event_loop()

    for account in accounts:
        is_valid = await loop.run_in_executor(
            None, _do_verify, account.service, account.api_key
        )
        account.is_valid = is_valid
        account.last_verified_at = datetime.now(timezone.utc)

        msg_map = {0: "失效", 1: "有效", 2: "无法确认"}
        results.append(VerifyResult(
            id=account.id,
            api_key=account.api_key,
            is_valid=is_valid,
            message=msg_map.get(is_valid, "未知"),
        ))

    await db.commit()
    return results
