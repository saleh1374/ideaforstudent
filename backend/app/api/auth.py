"""Auth endpoints (MVP: username login; OTP/SMS comes later)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthUser, get_current_user
from app.core.db import get_db
from app.core.security import make_token
from app.models.org import User

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


@router.post("/login")
async def login(body: LoginIn, db: AsyncSession = Depends(get_db)):
    user = (
        await db.execute(select(User).where(User.username == body.username))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="نام کاربری یا رمز نادرست است")
    # MVP: plain compare against seeded demo password; replace with passlib hash check
    from app.core.passwords import verify_password

    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="نام کاربری یا رمز نادرست است")
    return {"token": make_token(user.id), "user": {"id": user.id, "full_name": user.full_name, "role": user.system_role}}


@router.get("/me")
async def me(current: AuthUser = Depends(get_current_user)):
    return {"id": current.id, "username": current.username, "full_name": current.full_name, "role": current.system_role}
