"""Shared API dependencies."""
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.security import parse_token
from app.models.org import User
from app.services.rbac_service import has_permission_in_scope


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


def require_permission(permission_key: str, scope_type: str | None = None, scope_id: int | None = None, scope_param: str | None = None):
    """گارد دسترسی: کلید مجوز + بازه اعتبار (RBAC spec §9) + (در صورت تعریف)
    پوشش حوزه (RBAC spec §7): وقتی endpoint روی یک منبع حوزه‌مند است، حوزه
    مجوزِ تماس‌گیرنده باید آن منبع را بپوشاند.
    - scope_id: حوزه ثابت (مثلا national برای /geo/national/*)
    - scope_param: نام پارامتر مسیر/کوئری که شناسه هدف را می‌آورد (مثلا school_id)
    platform_admin از بررسی معاف است؛ انقضای مجوزها همچنان اعمال می‌شود."""

    async def _guard(
        current: AuthUser = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
        request: Request = None,
    ) -> AuthUser:
        if current.system_role == "platform_admin":
            return current

        target_type, target_id = scope_type, scope_id
        if target_id is None and scope_param is not None and request is not None:
            raw = request.path_params.get(scope_param)
            if raw is None:
                raw = request.query_params.get(scope_param)
            if raw is not None:
                try:
                    target_id = int(raw)
                except (TypeError, ValueError):
                    target_id = None

        allowed = await has_permission_in_scope(
            db,
            current.id,
            permission_key,
            target_type if target_id is not None else None,
            target_id,
        )
        if not allowed:
            raise HTTPException(status_code=403, detail=f"دسترسی لازم: {permission_key}")
        return current

    return _guard
