"""
FastAPI 应用工厂。
lifespan: 初始化 DB → 执行迁移 → 加载定时任务 → 启动 Scheduler
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from web.database import init_db, get_session_factory
from web.migration import run_all_migrations
from web.scheduler import init_scheduler, load_all_schedules, shutdown_scheduler

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动
    logger.info("[app] 初始化数据库表...")
    await init_db()

    logger.info("[app] 执行数据迁移...")
    factory = get_session_factory()
    async with factory() as session:
        await run_all_migrations(session)

    logger.info("[app] 启动定时任务调度器...")
    loop = asyncio.get_event_loop()
    init_scheduler(loop)
    await load_all_schedules()

    logger.info("[app] Web 服务已就绪")
    yield

    # 关闭
    shutdown_scheduler()
    logger.info("[app] Web 服务已停止")


def create_app() -> FastAPI:
    app = FastAPI(
        title="API Key 管理平台",
        description="自动注册平台账号、临时邮箱及 API Key 的 Web 管理界面",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
    )

    # 注册 routers
    from web.routers.auth import router as auth_router
    from web.routers.stats import router as stats_router
    from web.routers.accounts import router as accounts_router
    from web.routers.tasks import router as tasks_router
    from web.routers.mail_provider import router as mail_provider_router
    from web.routers.verify import router as verify_router
    from web.routers.schedule import router as schedule_router

    app.include_router(auth_router)
    app.include_router(stats_router)
    app.include_router(accounts_router)
    app.include_router(tasks_router)
    app.include_router(mail_provider_router)
    app.include_router(verify_router)
    app.include_router(schedule_router)

    # 挂载静态文件目录
    if _STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # 前端路由：所有非 /api 路径都返回对应的 HTML 文件
    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def index():
        return FileResponse(_STATIC_DIR / "index.html")

    @app.get("/accounts", response_class=HTMLResponse, include_in_schema=False)
    async def accounts_page():
        return FileResponse(_STATIC_DIR / "accounts.html")

    @app.get("/tasks", response_class=HTMLResponse, include_in_schema=False)
    async def tasks_page():
        return FileResponse(_STATIC_DIR / "tasks.html")

    @app.get("/mail", response_class=HTMLResponse, include_in_schema=False)
    async def mail_page():
        return FileResponse(_STATIC_DIR / "mail.html")

    @app.get("/mail-usages", response_class=HTMLResponse, include_in_schema=False)
    async def mail_usages_page():
        return FileResponse(_STATIC_DIR / "mail_usages.html")

    @app.get("/schedule", response_class=HTMLResponse, include_in_schema=False)
    async def schedule_page():
        return FileResponse(_STATIC_DIR / "schedule.html")

    @app.get("/login", response_class=HTMLResponse, include_in_schema=False)
    async def login_page():
        return FileResponse(_STATIC_DIR / "login.html")

    return app


app = create_app()
