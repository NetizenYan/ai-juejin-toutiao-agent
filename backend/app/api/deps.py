from fastapi import Header, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from backend.app.db.session import get_db
from backend.app.crud import users


# 整合 根据 Token 查询用户，返回用户
async def get_current_user(
        authorization: str | None = Header(None, alias="Authorization"),
        db: AsyncSession = Depends(get_db)
):
    # A missing header is "not logged in" (401), not a malformed request (422): the frontend
    # sends users to the login page on 401.
    if not authorization or not authorization.strip():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    token = authorization.replace("Bearer ", "").strip()
    user = await users.get_user_by_token(db, token)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的令牌或已经过期的令牌")

    return user
