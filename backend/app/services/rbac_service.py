"""RBAC service (RBAC spec §7, §8, §9): effective permissions with time
validity, scope containment (national ⊃ province ⊃ district ⊃ school ⊃
class ⊃ student) and grant/revoke with the golden rule «هیچ‌کس نمی‌تواند
دسترسی‌ای را به دیگری تفویض کند که خودش ندارد» — enforced in the backend,
not only the UI."""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.org import ClassRoom, District, School, StudentProfile, User
from app.models.rbac import AuditLog, Permission, PermissionAssignment, Role, RolePermission


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


async def active_assignments(
    db: AsyncSession,
    user_id: int,
    permission_key: str | None = None,
    on_date: date | None = None,
) -> list[tuple[PermissionAssignment, str]]:
    """تخصیص‌های فعال و معتبر از نظر زمان (RBAC spec §9 — دسترسی موقت).
    بازه null یعنی بدون محدودیت؛ تخصیصی که is_active مانده ولی از بازه بیرون
    است (منقضی یا هنوز شروع‌نشده) غیرفعال و با رویداد permission_expired در
    لاگ ممیزی ثبت می‌شود، و در این بررسی «داده‌شده» تلقی نمی‌شود."""
    on = on_date or date.today()
    q = (
        select(PermissionAssignment, Permission.key)
        .join(Permission, Permission.id == PermissionAssignment.permission_id)
        .where(
            PermissionAssignment.user_id == user_id,
            PermissionAssignment.is_active.is_(True),
        )
    )
    if permission_key is not None:
        q = q.where(Permission.key == permission_key)
    rows = list((await db.execute(q)).all())

    valid: list[tuple[PermissionAssignment, str]] = []
    expired: list[PermissionAssignment] = []
    for pa, key in rows:
        not_yet = pa.valid_from is not None and pa.valid_from > on
        past = pa.valid_until is not None and pa.valid_until < on
        if not_yet or past:
            expired.append(pa)
        else:
            valid.append((pa, key))

    if expired:
        for pa in expired:
            pa.is_active = False
            await log_action(
                db,
                actor_user_id=None,
                action="permission_expired",
                entity_type="permission_assignment",
                entity_id=pa.id,
                detail=(
                    f"user={pa.user_id} scope={pa.scope_type}:{pa.scope_id} "
                    f"valid_from={pa.valid_from} valid_until={pa.valid_until}"
                ),
            )
        # انقضا باید پایدار بماند، حتی اگر درخواست جاری بعداً rollback شود
        await db.commit()
    return valid


async def effective_permissions(db: AsyncSession, user_id: int, on_date: date | None = None) -> set[str]:
    """کلیدهای مجوز مؤثرِ کاربر — فقط بازه‌های اعتباردار (RBAC spec §9)."""
    rows = await active_assignments(db, user_id, on_date=on_date)
    return {key for _, key in rows}


async def user_scopes(db: AsyncSession, user_id: int, on_date: date | None = None) -> list[tuple[str, int]]:
    """حوزه‌های (scope_type, scope_id) فعال و اعتباردار کاربر."""
    rows = await active_assignments(db, user_id, on_date=on_date)
    return sorted({(pa.scope_type, pa.scope_id) for pa, _ in rows})


async def scope_chain(db: AsyncSession, scope_type: str | None, scope_id: int | None) -> list[tuple[str, int]]:
    """زنجیره سلسله‌مراتبیِ هدف از کلی به جزئی. حوزه‌ای که در زنجیره هدف باشد
    هدف را می‌پوشاند: national همه‌چیز؛ province ناحیه/مدرسه‌های استان؛
    district مدرسه‌های ناحیه؛ school کلاس/دانش‌آموزهای همان مدرسه."""
    chain: list[tuple[str, int]] = [("national", 0)]
    if scope_type in (None, "national") or scope_id is None:
        return chain
    if scope_type == "province":
        return chain + [("province", scope_id)]
    if scope_type == "district":
        district = await db.get(District, scope_id)
        if district is not None:
            chain.append(("province", district.province_id))
        return chain + [("district", scope_id)]
    if scope_type == "school":
        school = await db.get(School, scope_id)
        if school is not None:
            chain += [("province", school.province_id), ("district", school.district_id)]
        return chain + [("school", scope_id)]
    if scope_type == "class":
        class_room = await db.get(ClassRoom, scope_id)
        base = await scope_chain(db, "school", class_room.school_id) if class_room is not None else chain
        return base + [("class", scope_id)]
    if scope_type == "student":
        profile = (
            await db.execute(select(StudentProfile).where(StudentProfile.user_id == scope_id))
        ).scalar_one_or_none()
        if profile is not None and profile.class_id is not None:
            base = await scope_chain(db, "class", profile.class_id)
        elif profile is not None:
            base = await scope_chain(db, "school", profile.school_id)
        else:
            base = chain
        return base + [("student", scope_id)]
    # نوع حوزه ناشناخته → فقط خودش
    return chain + [(scope_type, scope_id)]


async def _is_platform_admin(db: AsyncSession, user_id: int) -> bool:
    user = await db.get(User, user_id)
    return user is not None and user.system_role == "platform_admin"


async def has_permission(db: AsyncSession, user_id: int, permission_key: str, on_date: date | None = None) -> bool:
    """آیا کاربر این مجوز را (در هر حوزه‌ای) دارد؟ platform_admin عبور می‌کند."""
    if await _is_platform_admin(db, user_id):
        return True
    rows = await active_assignments(db, user_id, permission_key, on_date=on_date)
    return bool(rows)


async def has_permission_in_scope(
    db: AsyncSession,
    user_id: int,
    permission_key: str,
    scope_type: str | None = None,
    scope_id: int | None = None,
    on_date: date | None = None,
) -> bool:
    """آیا حداقل یک تخصیصِ اعتباردارِ این مجوز، حوزه هدف را می‌پوشاند؟
    بدون حوزه هدف → فقط وجود محفظه (scope_type=None) کافی است."""
    if await _is_platform_admin(db, user_id):
        return True
    rows = await active_assignments(db, user_id, permission_key, on_date=on_date)
    if not rows:
        return False
    if scope_type is None or scope_id is None:
        return True
    chain = await scope_chain(db, scope_type, scope_id)
    return any((pa.scope_type, pa.scope_id) in chain for pa, _ in rows)


async def grants_of(
    db: AsyncSession,
    user_id: int,
    permission_key: str,
    on_date: date | None = None,
) -> list[tuple[str, int]]:
    """همه حوزه‌های اعتباردارِ این مجوز برای کاربر."""
    if await _is_platform_admin(db, user_id):
        return [("national", 0)]
    rows = await active_assignments(db, user_id, permission_key, on_date=on_date)
    return [(pa.scope_type, pa.scope_id) for pa, _ in rows]


async def covering_grants(
    db: AsyncSession,
    user_id: int,
    permission_key: str,
    scope_type: str | None,
    scope_id: int | None,
    on_date: date | None = None,
) -> list[tuple[str, int]]:
    """حوزه‌هایی از مجوز که هدف داده‌شده را می‌پوشانند."""
    if await _is_platform_admin(db, user_id):
        return [("national", 0)]
    rows = await active_assignments(db, user_id, permission_key, on_date=on_date)
    if not rows:
        return []
    if scope_type is None or scope_id is None:
        return [(pa.scope_type, pa.scope_id) for pa, _ in rows]
    chain = await scope_chain(db, scope_type, scope_id)
    return [(pa.scope_type, pa.scope_id) for pa, _ in rows if (pa.scope_type, pa.scope_id) in chain]


async def visible_school_ids(
    db: AsyncSession,
    user_id: int,
    permission_key: str,
    on_date: date | None = None,
) -> set[int] | None:
    """شناسه مدارسی که کاربر با این مجوز دید دارد؛ None یعنی دید سراسری
    (platform_admin یا حوزه national). برای فیلتر کردن فهرست‌ها به کار می‌رود."""
    if await _is_platform_admin(db, user_id):
        return None
    rows = await active_assignments(db, user_id, permission_key, on_date=on_date)
    if any(pa.scope_type == "national" for pa, _ in rows):
        return None
    if not rows:
        return set()
    schools = (await db.execute(select(School))).scalars().all()
    result: set[int] = set()
    for pa, _ in rows:
        scope_type, scope_id = pa.scope_type, pa.scope_id
        if scope_type == "province":
            result |= {sc.id for sc in schools if sc.province_id == scope_id}
        elif scope_type == "district":
            result |= {sc.id for sc in schools if sc.district_id == scope_id}
        elif scope_type == "school":
            result.add(scope_id)
        elif scope_type == "class":
            class_room = await db.get(ClassRoom, scope_id)
            if class_room is not None:
                result.add(class_room.school_id)
        elif scope_type == "student":
            profile = (
                await db.execute(select(StudentProfile).where(StudentProfile.user_id == scope_id))
            ).scalar_one_or_none()
            if profile is not None:
                result.add(profile.school_id)
    return result


async def check_delegation_scope(
    db: AsyncSession,
    *,
    grantor_user_id: int,
    grantee_user_id: int | None,
    permission_key: str,
    scope_type: str,
    scope_id: int,
) -> dict:
    """پیش‌بررسی قاعده طلایی پیش از ایجاد رکورد: تفویض‌کننده باید خودش همین
    مجوز را در حوزه‌ای که هدف را بپوشاند داشته باشد (RBAC spec §8). در ردّی
    لاگ ممیزی delegation_denied_insufficient_owner_permission ثبت می‌شود."""
    if await _is_platform_admin(db, grantor_user_id):
        return {"ok": True, "reason": None}
    rows = await active_assignments(db, grantor_user_id, permission_key)
    chain = await scope_chain(db, scope_type, scope_id)
    if any((pa.scope_type, pa.scope_id) in chain for pa, _ in rows):
        return {"ok": True, "reason": None}
    await log_action(
        db,
        actor_user_id=grantor_user_id,
        action="delegation_denied_insufficient_owner_permission",
        entity_type="user",
        entity_id=grantee_user_id,
        detail=f"permission={permission_key} scope={scope_type}:{scope_id}",
    )
    return {"ok": False, "reason": "شما خودتان این دسترسی را در این حوزه ندارید"}


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
    """Grant with golden-rule + scope check. Returns {ok, reason}."""
    perm = await db.get(Permission, permission_id)
    if perm is None:
        return {"ok": False, "reason": "مجوز یافت نشد", "not_found": True}
    perm_key = perm.key

    # قاعده طلایی: مجوزِ واگذارشده باید در حوزه‌ای باشد که تفویض‌کننده دارد
    check = await check_delegation_scope(
        db,
        grantor_user_id=grantor_user_id,
        grantee_user_id=grantee_user_id,
        permission_key=perm_key,
        scope_type=scope_type,
        scope_id=scope_id,
    )
    if not check["ok"]:
        return check

    # نقش باید واقعاً مجوز را داشته باشد (بارگذاری صریح — بارگذاری تنبل
    # در session ناهمگام MissingGreenlet می‌دهد)
    role = await db.get(Role, role_id)
    if role is None:
        return {"ok": False, "reason": "نقش یافت نشد", "not_found": True}
    role_perm_keys = {
        key
        for (key,) in (
            await db.execute(
                select(Permission.key)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .where(RolePermission.role_id == role_id)
            )
        ).all()
    }
    if perm_key not in role_perm_keys:
        return {"ok": False, "reason": "این مجوز به نقش تعلق ندارد"}

    existing = (
        await db.execute(
            select(PermissionAssignment).where(
                PermissionAssignment.user_id == grantee_user_id,
                PermissionAssignment.role_id == role_id,
                PermissionAssignment.permission_id == permission_id,
                PermissionAssignment.scope_type == scope_type,
                PermissionAssignment.scope_id == scope_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.is_active:
            return {"ok": True, "reason": None}
        # تخصیص منقضی‌شده قبلی → احیا با شرایط جدید
        existing.is_active = True
        existing.delegated_by = grantor_user_id
        existing.valid_from = valid_from
        existing.valid_until = valid_until
    else:
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
    """لغو فقط با اختیار manage_permissions در حوزه‌ای که خودِ تخصیص را
    بپوشاند (یا platform_admin) — «same-scope admin» (RBAC spec §8)."""
    pa = await db.get(PermissionAssignment, assignment_id)
    if pa is None:
        return {"ok": False, "reason": "یافت نشد", "not_found": True}

    if not await _is_platform_admin(db, actor_user_id):
        grants = await covering_grants(db, actor_user_id, "manage_permissions", pa.scope_type, pa.scope_id)
        if not grants:
            await log_action(
                db,
                actor_user_id=actor_user_id,
                action="delegation_denied_insufficient_owner_permission",
                entity_type="user",
                entity_id=pa.user_id,
                detail=f"revoke assignment={assignment_id} scope={pa.scope_type}:{pa.scope_id}",
            )
            return {
                "ok": False,
                "reason": "شما در این حوزه اختیار لغو این دسترسی را ندارید",
                "not_found": False,
            }

    pa.is_active = False
    await log_action(
        db,
        actor_user_id=actor_user_id,
        action="permission_revoked",
        entity_type="user",
        entity_id=pa.user_id,
        detail=f"assignment={assignment_id}",
    )
    return {"ok": True, "reason": None, "not_found": False}
