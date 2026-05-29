from fastapi import APIRouter, HTTPException, status
from web.auth import create_access_token, verify_credentials
from web.schemas import LoginRequest, TokenResponse

router = APIRouter(prefix="/api", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    if not verify_credentials(req.username, req.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )
    token = create_access_token(req.username)
    return TokenResponse(access_token=token)
