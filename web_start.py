#!/usr/bin/env python
"""
Web 管理服务启动入口。
用法:
    python web_start.py
    WEB_PORT=8086 python web_start.py
"""
import logging
import os
import sys
from pathlib import Path

# 确保项目根目录在 sys.path
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

import config as _cfg


def _check_deps():
    missing = []
    for pkg in ("fastapi", "uvicorn", "sqlalchemy", "jose", "apscheduler", "sse_starlette"):
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"[ERROR] 缺少依赖包: {missing}")
        print("请运行: pip install -r requirements.txt")
        sys.exit(1)


def main():
    _check_deps()

    import uvicorn

    host = os.getenv("WEB_HOST", "0.0.0.0")
    port = _cfg.WEB_PORT

    print(f"""
╔══════════════════════════════════════════════════╗
║           API Key 管理平台  v1.0.0               ║
╠══════════════════════════════════════════════════╣
║  地址:  http://{host}:{port:<5}                      ║
║  数据库: {_cfg.DB_TYPE:<10}                           ║
║  用户名: {_cfg.WEB_ADMIN_USER:<10}                   ║
╚══════════════════════════════════════════════════╝
    """)

    uvicorn.run(
        "web.app:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
        access_log=True,
    )


if __name__ == "__main__":
    main()
