"""
数据库引擎工厂。
根据 DB_TYPE 环境变量自动选择 SQLite (aiosqlite) 或 PostgreSQL (asyncpg)。
"""
from __future__ import annotations

import sys
import os
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

# 将项目根目录加入 sys.path，确保 config 可导入
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config as _cfg


def _build_url() -> str:
    db_type = _cfg.DB_TYPE
    if db_type == "postgresql":
        url = _cfg.DB_URL
        if not url:
            raise ValueError("DB_TYPE=postgresql 但 DB_URL 未配置，请在 .env 中设置 DB_URL")
        # 确保使用 asyncpg 驱动
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        return url
    else:
        # SQLite 默认
        db_path = Path(_cfg.DB_PATH)
        if not db_path.is_absolute():
            db_path = _ROOT / db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite+aiosqlite:///{db_path}"


def _create_engine():
    url = _build_url()
    if _cfg.DB_TYPE == "postgresql":
        return create_async_engine(
            url,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            echo=False,
        )
    else:
        return create_async_engine(
            url,
            connect_args={"check_same_thread": False},
            echo=False,
        )


# 全局引擎和 session 工厂（延迟初始化，首次访问时创建）
_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = _create_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _SessionLocal


async def get_db() -> AsyncSession:
    """FastAPI 依赖注入用的 DB session 生成器。"""
    factory = get_session_factory()
    async with factory() as session:
        yield session


class Base(DeclarativeBase):
    pass


async def init_db():
    """创建所有表（幂等，使用 CREATE TABLE IF NOT EXISTS 语义）。"""
    from web.models import Account, Task, TaskLog, MailProvider, EmailUsage, Schedule  # noqa: F401
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
