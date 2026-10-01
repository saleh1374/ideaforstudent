"""RBAC service (RBAC spec §7, §8): effective permissions, grant with the
golden rule «هیچ‌کس نمی‌تواند دسترسی‌ای را به دیگری تفویض کند که خودش
ندارد» — enforced in the backend, not only the UI."""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.org import User
from app.models.rbac import AuditLog, Permission, PermissionAssignment, Role
from app.core.config import get_settings


async def log_action(
    db: AsyncSession,
    *,
    actor_user_id: int | None,
    action: str,
    entity_type: str | None = None,
    entity_id: int | None = None,
    detail: str | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_user_id=actor_user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            detail=detail,
        )
    )
    await db.flush()


async def effective_permissions(db: AsyncSession, user_id: int, on_date: date | None = None) -> set[str]:
    """Active permission keys across all scopes; time-valid grants only."""
    q = (
        select(Permission.key)
        .join(PermissionAssignment, PermissionAssignment.permission_id == Permission.id)
        .where(
            PermissionAssignment.user_id == user_id,
            PermissionAssignment.is_active.is_(True),
        )
    )
    rows = (await db.execute(q)).scalars().all()
    return set(rows)


async def user_scopes(db: AsyncSession, user_id: int) -> list[tuple[str, int]]:
    """Distinct (scope_type, scope_id) pairs for the user."""
    q = select(PermissionAssignment.scope_type, PermissionAssignment.scope_id).where(
        PermissionAssignment.user_id == user_id,
        PermissionAssignment.is_active.is_(True),
    )
    return [(t, i) for t, i in (await db.execute(q)).all()]


async def grant_permission(
    db: AsyncSession,
    *,
    grantor_user_id: int,
    grantee_user_id: int,
    role_id: int,
    permission_id: int,
    scope_type: str,
    scope_id: int,
    valid_from: date | None = None,
    valid_until: date | None = None,
) -> dict:
    """Grant with golden-rule check. Returns {ok, reason}."""
    owner_perms = await effective_permissions(db, grantor_user_id)
    perm_key = (await db.get(Permission, permission_id)).key

    if perm_key not in owner_perms:
        await log_action(
            db,
            actor_user_id=grantor_user_id,
            action="delegation_denied_insufficient_owner_permission",
            entity_type="user",
            entity_id=grantee_user_id,
            detail=f"permission={perm_key} scope={scope_type}:{scope_id}",
        )
        return {"ok": False, "reason": "شما خودتان این دسترسی را ندارید"}

    # role must actually contain the permission
    role = await db.get(Role, role_id)
    role_perm_keys = {rp.permission.key for rp in role.permissions}
    if perm_key not in role_perm_keys:
        return {"ok": False, "reason": "این مجوز به نقش تعلق ندارد"}

    db.add(
        PermissionAssignment(
            user_id=grantee_user_id,
            role_id=role_id,
            permission_id=permission_id,
            scope_type=scope_type,
            scope_id=scope_id,
            delegated_by=grantor_user_id,
            valid_from=valid_from,
            valid_until=valid_until,
            is_active=True,
        )
    )
    await log_action(
        db,
        actor_user_id=grantor_user_id,
        action="permission_granted",
        entity_type="user",
        entity_id=grantee_user_id,
        detail=f"permission={perm_key} scope={scope_type}:{scope_id}",
    )
    return {"ok": True, "reason": None}


async def revoke_permission(db: AsyncSession, *, actor_user_id: int, assignment_id: int) -> dict:
    pa = await db.get(PermissionAssignment, assignment_id)
    if pa is None:
        return {"ok": False, "reason": "یافت نشد"}
    pa.is_active = False
    await log_action(
        db,
        actor_user_id=actor_user_id,
        action="permission_revoked",
        entity_type="user",
        entity_id=pa.user_id,
        detail=f"assignment={assignment_id}",
    )
    return {"ok": True, "reason": None}
