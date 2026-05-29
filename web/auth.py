"""
JWT 登录认证。
用户名/密码来自 .env (WEB_ADMIN_USER / WEB_ADMIN_PASSWORD)。
Token 过期时间默认 24 小时，可通过 WEB_TOKEN_EXPIRE_HOURS 调整。
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config as _cfg

try:
    from jose import JWTError, jwt
except ImportError:
    raise ImportError("请安装 python-jose: pip install python-jose[cryptography]")

_ALGORITHM = "HS256"
_bearer_scheme = HTTPBearer(auto_error=False)


def _expire_hours() -> int:
    import os
    try:
        return int(os.getenv("WEB_TOKEN_EXPIRE_HOURS", "24"))
    except (ValueError, TypeError):
        return 24


def create_access_token(username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=_expire_hours())
    payload = {"sub": username, "exp": expire}
    return jwt.encode(payload, _cfg.WEB_SECRET_KEY, algorithm=_ALGORITHM)


def verify_credentials(username: str, password: str) -> bool:
    return (
        username == _cfg.WEB_ADMIN_USER
        and password == _cfg.WEB_ADMIN_PASSWORD
    )


def decode_token(token: str) -> Optional[str]:
    """解码并验证 JWT，返回 username 或 None。"""
    try:
        payload = jwt.decode(token, _cfg.WEB_SECRET_KEY, algorithms=[_ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> str:
    """FastAPI 依赖：校验 Bearer token，返回用户名。"""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证 Token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    username = decode_token(credentials.credentials)
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return username
