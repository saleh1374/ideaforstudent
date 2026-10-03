"""RBAC service (RBAC spec §7, §8, §9): effective permissions with time
validity, scope containment (national ⊃ province ⊃ district ⊃ school ⊃
class ⊃ student) and grant/revoke with the golden rule «هیچ‌کس نمی‌تواند
دسترسی‌ای را به دیگری تفویض کند که خودش ندارد» — enforced in the backend,
not only the UI."""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.org import (
    ClassRoom,
    ClassTeacherAssignment,
    District,
    Employee,
    School,
    SchoolAssignment,
    StudentProfile,
    User,
)
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


# ==============================================================================
# خواندن دسترسی‌ها و لاگ ممیزی (RBAC §17/§18) — رابطِ UI واگذاری و ممیزی
# ==============================================================================

SCOPE_TYPES = ("province", "district", "school", "class", "student", "national")


async def permissions_catalog(db: AsyncSession) -> dict:
    """فهرست کامل مجوزها، نقش‌ها و اینکه هر نقش پیش‌فرض چه مجوزهایی دارد —
    ورودی فهرستِ انتخاب در UI واگذاری مجوز (RBAC §7)."""
    perms = list((await db.execute(select(Permission).order_by(Permission.key))).scalars())
    roles = list((await db.execute(select(Role).order_by(Role.id))).scalars())
    role_perms = list((await db.execute(select(RolePermission))).scalars())

    by_role: dict[int, list[str]] = {r.id: [] for r in roles}
    for rp in role_perms:
        by_role.setdefault(rp.role_id, []).append(rp.permission_id)
    perm_titles = {p.id: (p.key, p.title_fa) for p in perms}

    return {
        "permissions": [{"id": p.id, "key": p.key, "title_fa": p.title_fa} for p in perms],
        "roles": [
            {
                "id": r.id,
                "key": r.key,
                "title_fa": r.title_fa,
                "permissions": sorted(
                    perm_titles[pid][0] for pid in by_role.get(r.id, []) if pid in perm_titles
                ),
            }
            for r in roles
        ],
        "scope_types": list(SCOPE_TYPES),
        "note_fa": "حوزه‌ها: استان ← ناحیه ← مدرسه ← کلاس ← دانش‌آموز؛ تفویض هرگز بزرگ‌تر از مجوز خودِ تفویض‌کننده نمی‌شود.",
    }


async def _scope_school_ids(db: AsyncSession, scope_type: str, scope_id: int) -> set[int]:
    """حوزهٔ یک تخصیص → مدارسی که آن حوزه می‌پوشاند (برای فیلتر دید بیننده)."""
    if scope_type == "school":
        return {scope_id}
    if scope_type == "class":
        cls = await db.get(ClassRoom, scope_id)
        return {cls.school_id} if cls else set()
    if scope_type == "student":
        profile = (
            await db.execute(select(StudentProfile).where(StudentProfile.user_id == scope_id))
        ).scalar_one_or_none()
        return {profile.school_id} if profile else set()
    schools = list((await db.execute(select(School))).scalars())
    if scope_type == "district":
        return {s.id for s in schools if s.district_id == scope_id}
    if scope_type == "province":
        return {s.id for s in schools if s.province_id == scope_id}
    if scope_type == "national":
        return {s.id for s in schools}
    return set()


async def permission_assignments(
    db: AsyncSession,
    viewer_user_id: int,
    *,
    permission_key: str | None = None,
) -> dict:
    """همهٔ تخصیص‌های مجوز با نام کاربر/نقش/مجوز — فقط حوزه‌هایی که برای
    بیننده قابل مشاهده‌اند (هیچ حوزهٔ خارج از دید برنمی‌گردد)."""
    visible = await visible_school_ids(db, viewer_user_id, "manage_permissions")
    if visible is None:
        visible = await visible_school_ids(db, viewer_user_id, "view_school_analytics")
    broad_viewer = visible is None

    q = select(PermissionAssignment).order_by(PermissionAssignment.id.desc())
    if permission_key is not None:
        q = q.join(Permission, Permission.id == PermissionAssignment.permission_id).where(
            Permission.key == permission_key
        )
    rows = list((await db.execute(q)).scalars())

    perm_map = {p.id: p for p in (await db.execute(select(Permission))).scalars()}
    role_map = {r.id: r for r in (await db.execute(select(Role))).scalars()}
    user_ids = sorted({r.user_id for r in rows} | {r.delegated_by for r in rows if r.delegated_by} | {viewer_user_id})
    users = {
        u.id: u
        for u in (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars()
    } if user_ids else {}

    out: list[dict] = []
    for pa in rows:
        if not broad_viewer:
            covered = await _scope_school_ids(db, pa.scope_type, pa.scope_id)
            if not (covered & visible):
                continue
        perm = perm_map.get(pa.permission_id)
        role = role_map.get(pa.role_id)
        user = users.get(pa.user_id)
        delegator = users.get(pa.delegated_by) if pa.delegated_by else None
        out.append(
            {
                "id": pa.id,
                "user_id": pa.user_id,
                "user_name": user.full_name if user else f"#{pa.user_id}",
                "username": user.username if user else None,
                "permission": perm.key if perm else None,
                "permission_fa": perm.title_fa if perm else None,
                "role": role.key if role else None,
                "role_fa": role.title_fa if role else None,
                "scope_type": pa.scope_type,
                "scope_id": pa.scope_id,
                "delegated_by": pa.delegated_by,
                "delegated_by_name": delegator.full_name if delegator else None,
                "valid_from": pa.valid_from.isoformat() if pa.valid_from else None,
                "valid_until": pa.valid_until.isoformat() if pa.valid_until else None,
                "is_active": pa.is_active,
                "created_at": pa.created_at.isoformat() if pa.created_at else None,
            }
        )
    return {
        "assignments": out,
        "all_scopes": broad_viewer,
        "note_fa": "تخصیص‌های خارج از حوزهٔ دید شما در این فهرست نمی‌آیند.",
    }


async def _actors_in_schools(db: AsyncSession, school_ids: set[int]) -> set[int]:
    """کاربرانی که به یکی از این مدارس وابسته‌اند (دانش‌آموز، کادر، معلم کلاس)."""
    if not school_ids:
        return set()
    actors: set[int] = {
        p.user_id
        for p in (
            await db.execute(select(StudentProfile).where(StudentProfile.school_id.in_(school_ids)))
        ).scalars()
    }
    staff_rows = (
        await db.execute(
            select(Employee.user_id)
            .join(SchoolAssignment, SchoolAssignment.employee_id == Employee.id)
            .where(SchoolAssignment.school_id.in_(school_ids))
        )
    ).scalars().all()
    actors |= set(staff_rows)
    teacher_rows = (
        await db.execute(
            select(ClassTeacherAssignment.teacher_user_id)
            .join(ClassRoom, ClassRoom.id == ClassTeacherAssignment.class_id)
            .where(ClassRoom.school_id.in_(school_ids))
        )
    ).scalars().all()
    actors |= set(teacher_rows)
    return actors


async def audit_logs(
    db: AsyncSession,
    viewer_user_id: int,
    *,
    action: str | None = None,
    limit: int = 100,
) -> dict:
    """§17/§18 خواندن لاگ ممیزی: فقط برای دارندهٔ manage_permissions و فقط در
    حوزهٔ دیدش — بینندهٔ مدرسه‌ای رویدادهای مربوط به مدارس خودش را می‌بیند؛
    platform_admin و حوزهٔ national همه را می‌بینند. هر بازدید خودش رویداد
    audit_log_viewed ثبت می‌کند."""
    visible = await visible_school_ids(db, viewer_user_id, "manage_permissions")
    broad = visible is None

    q = select(AuditLog).order_by(AuditLog.id.desc()).limit(max(1, min(limit, 500)))
    if action is not None:
        q = q.where(AuditLog.action == action)
    rows = list((await db.execute(q)).scalars())

    allowed_actors: set[int] | None = None
    if not broad:
        allowed_actors = await _actors_in_schools(db, visible)
        allowed_actors.add(viewer_user_id)

    logs = []
    for r in rows:
        if allowed_actors is not None:
            if r.actor_user_id is None or r.actor_user_id not in allowed_actors:
                continue
        actor = await db.get(User, r.actor_user_id) if r.actor_user_id else None
        logs.append(
            {
                "id": r.id,
                "actor_id": r.actor_user_id,
                "actor_name": actor.full_name if actor else (f"#{r.actor_user_id}" if r.actor_user_id else "سیستم"),
                "action": r.action,
                "entity_type": r.entity_type,
                "entity_id": r.entity_id,
                "detail": r.detail,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
        )
    return {
        "logs": logs,
        "all_scopes": broad,
        "count": len(logs),
        "note_fa": "لاگ ممیزی فقط‌خواندنی است؛ هر ثبت/حذف مجوز و هر بازدید حساس خودش در آن ثبت می‌شود.",
    }
