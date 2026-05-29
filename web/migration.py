"""
幂等数据迁移：将现有 .txt 文件中的账号数据导入 SQLite/PostgreSQL。
已存在的记录（通过 service + api_key 唯一约束）会被跳过。
同时迁移 onlinemail_orders.txt 中的邮箱订单。
"""
from __future__ import annotations

import logging
from pathlib import Path
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# 项目根目录
_ROOT = Path(__file__).resolve().parent.parent

# 各平台 txt 文件映射
_SERVICE_FILES = {
    "tavily":    "accounts.txt",
    "firecrawl": "firecrawl_accounts.txt",
    "exa":       "exa_accounts.txt",
    "you":       "you_accounts.txt",
    "serper":    "serper_accounts.txt",
    "valyu":     "valyu_accounts.txt",
}

_ONLINEMAIL_FILE = "onlinemail_orders.txt"


async def migrate_accounts(session: AsyncSession) -> int:
    """将各平台 txt 文件中的账号迁移到 DB，返回新增条数。"""
    from web.models import Account

    total_inserted = 0

    for service, filename in _SERVICE_FILES.items():
        filepath = _ROOT / filename
        if not filepath.exists():
            continue

        lines = filepath.read_text(encoding="utf-8").splitlines()
        for line in lines:
            line = line.strip()
            if not line:
                continue

            parts = line.split(",")
            if len(parts) < 3:
                continue

            email = parts[0].strip()
            password = parts[1].strip() or None
            api_key = parts[2].strip()

            if not email or not api_key:
                continue

            # 检查是否已存在
            result = await session.execute(
                select(Account).where(
                    Account.service == service,
                    Account.api_key == api_key,
                )
            )
            if result.scalar_one_or_none() is not None:
                continue

            account = Account(
                service=service,
                email=email,
                password=password,
                api_key=api_key,
                is_valid=2,  # 未验证
                uploaded=False,
            )
            session.add(account)
            try:
                await session.flush()
                total_inserted += 1
            except IntegrityError:
                await session.rollback()

    await session.commit()
    if total_inserted:
        logger.info(f"[migration] 账号迁移完成，新增 {total_inserted} 条")
    return total_inserted


async def run_all_migrations(session: AsyncSession):
    """执行全部迁移，启动时调用。"""
    accounts = await migrate_accounts(session)
    logger.info(f"[migration] 完成：账号 +{accounts}")
