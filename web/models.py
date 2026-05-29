"""
SQLAlchemy ORM 模型定义。
所有表均使用 IF NOT EXISTS 语义（由 Base.metadata.create_all 保证）。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from web.database import Base


class Account(Base):
    """已注册的平台账号及 API Key。"""
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("service", "api_key", name="uq_service_apikey"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    service: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(256), nullable=False)
    password: Mapped[str | None] = mapped_column(String(256), nullable=True)
    api_key: Mapped[str] = mapped_column(String(512), nullable=False)
    # 0=失效  1=有效  2=未验证
    is_valid: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    uploaded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Task(Base):
    """注册任务记录。"""
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    service: Mapped[str] = mapped_column(String(32), nullable=False)
    total: Mapped[int] = mapped_column(Integer, nullable=False)
    concurrency: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    delay: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # pending / running / done / cancelled / failed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    upload: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    logs: Mapped[list[TaskLog]] = relationship(
        "TaskLog", back_populates="task", cascade="all, delete-orphan"
    )


class TaskLog(Base):
    """任务实时日志（SSE 游标增量拉取）。"""
    __tablename__ = "task_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    level: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    task: Mapped[Task] = relationship("Task", back_populates="logs")


class MailProvider(Base):
    """邮件服务商配置（在平台管理界面维护，不再依赖 .env）。"""
    __tablename__ = "mail_providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # cloudflare | duckmail | onlinemail
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    # JSON 字符串存储提供商特定参数
    config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 仅 onlinemail 使用：预购邮箱的剩余订单（每行 email----orderId）
    orders_pool: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    usages: Mapped[list[EmailUsage]] = relationship(
        "EmailUsage", back_populates="provider", cascade="all, delete-orphan"
    )


class EmailUsage(Base):
    """每一个邮箱的使用追踪记录。"""
    __tablename__ = "email_usages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("mail_providers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 使用该邮箱的 task_id（可为空，表示非 Web 触发）
    task_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    email: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    # onlinemail 订单号，其他 provider 为空
    order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # 用于注册哪个平台
    target_service: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    # pending / success / failed / cancelled
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    # 注册成功后获得的 api_key（成功时填充）
    api_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # 失败原因摘要
    fail_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    provider: Mapped[MailProvider] = relationship("MailProvider", back_populates="usages")


class Schedule(Base):
    """定时注册任务配置。"""
    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    service: Mapped[str] = mapped_column(String(32), nullable=False)
    cron_expr: Mapped[str] = mapped_column(String(64), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    concurrency: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    delay: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    upload: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
