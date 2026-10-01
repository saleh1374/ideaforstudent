"""Shared API dependencies."""
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.security import parse_token
from app.models.org import User
from app.models.rbac import Permission, PermissionAssignment


@dataclass
class AuthUser:
    id: int
    username: str
    full_name: str
    system_role: str


async def get_current_user(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> AuthUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="توکن ارسال نشده است")
    token = authorization.split(" ", 1)[1]
    user_id = parse_token(token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="توکن نامعتبر است")
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="کاربر یافت نشد")
    return AuthUser(id=user.id, username=user.username, full_name=user.full_name, system_role=user.system_role)


def require_permission(permission_key: str):
    async def _guard(
        current: AuthUser = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> AuthUser:
        allowed = (
            await db.execute(
                select(PermissionAssignment.id)
                .join(Permission, Permission.id == PermissionAssignment.permission_id)
                .where(
                    PermissionAssignment.user_id == current.id,
                    Permission.key == permission_key,
                    PermissionAssignment.is_active.is_(True),
                )
            )
        ).first()
        if allowed is None and current.system_role != "platform_admin":
            raise HTTPException(status_code=403, detail=f"دسترسی لازم: {permission_key}")
        return current
    return _guard
