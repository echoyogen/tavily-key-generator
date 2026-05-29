"""
Pydantic 请求/响应模型。
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# ─── 认证 ────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ─── 账号 ────────────────────────────────────────────────────────────────────

class AccountOut(BaseModel):
    id: int
    service: str
    email: str
    password: Optional[str]
    api_key: str
    is_valid: int          # 0=失效 1=有效 2=未验证
    last_verified_at: Optional[datetime]
    created_at: datetime
    uploaded: bool

    model_config = {"from_attributes": True}

class AccountListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[AccountOut]


# ─── 任务 ────────────────────────────────────────────────────────────────────

class TaskCreateRequest(BaseModel):
    service: str = Field(..., description="平台名称: tavily/firecrawl/exa/you/serper/valyu")
    count: int = Field(..., ge=1, le=500)
    concurrency: int = Field(2, ge=1, le=20)
    delay: int = Field(0, ge=0, le=300, description="任务间隔秒数")
    upload: bool = False

class TaskOut(BaseModel):
    id: int
    service: str
    total: int
    concurrency: int
    delay: int
    success: int
    failed: int
    status: str
    upload: bool
    created_at: datetime
    finished_at: Optional[datetime]

    model_config = {"from_attributes": True}

class TaskLogOut(BaseModel):
    id: int
    task_id: int
    level: str
    message: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── 邮箱订单 ────────────────────────────────────────────────────────────────

class MailOrderOut(BaseModel):
    id: int
    email: str
    order_id: str
    used: bool
    created_at: datetime

    model_config = {"from_attributes": True}

class MailOrderBulkCreate(BaseModel):
    lines: str = Field(..., description="每行格式: email----orderId，支持多行批量粘贴")


# ─── Key 验证 ─────────────────────────────────────────────────────────────────

class VerifyRequest(BaseModel):
    ids: Optional[List[int]] = None        # 指定账号 ID 列表
    service: Optional[str] = None          # 验证整个平台
    all: bool = False                      # service + all=True 验证该平台所有账号

class VerifyResult(BaseModel):
    id: int
    api_key: str
    is_valid: int
    message: str


# ─── 统计 ────────────────────────────────────────────────────────────────────

class ServiceStats(BaseModel):
    service: str
    total: int
    valid: int
    invalid: int
    unverified: int
    today_new: int

class StatsResponse(BaseModel):
    services: List[ServiceStats]
    total_accounts: int
    total_valid: int
    pending_tasks: int
    running_tasks: int


# ─── 定时任务 ────────────────────────────────────────────────────────────────

class ScheduleCreateRequest(BaseModel):
    service: str
    cron_expr: str = Field(..., description="标准 5 段 cron 表达式，如 '0 2 * * *'")
    count: int = Field(1, ge=1)
    concurrency: int = Field(2, ge=1, le=20)
    delay: int = Field(0, ge=0)
    upload: bool = False
    enabled: bool = True

class ScheduleUpdateRequest(BaseModel):
    cron_expr: Optional[str] = None
    count: Optional[int] = None
    concurrency: Optional[int] = None
    delay: Optional[int] = None
    upload: Optional[bool] = None
    enabled: Optional[bool] = None

class ScheduleOut(BaseModel):
    id: int
    service: str
    cron_expr: str
    count: int
    concurrency: int
    delay: int
    upload: bool
    enabled: bool
    last_run_at: Optional[datetime]
    next_run_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}
