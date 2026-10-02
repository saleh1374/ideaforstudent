"""مهاجرت idempotent پنل کامل مدیر مدرسه روی DB موجود (بدون seed مجدد):

۱) جدول‌های جدید SchoolShift / ClassScheduleEntry را می‌سازد (create_all)؛
۲) مجوز manage_school_ops را اضافه و به نقش/کاربران ذی‌ربط تخصیص می‌دهد؛
۳) شیفت‌های نمونه مدرسه ۱ (تک‌شیفت) و مدرسه ۲ (دوشیفت) را درج می‌کند؛
۴) برنامه هفتگی نمونه کلاس‌ها را درج می‌کند.

همه مراحل شرطی/یکتایند؛ اجرای دوباره خطا نمی‌دهد.

Usage: python -m scripts.migrate_school_ops
"""
from __future__ import annotations

import asyncio
from datetime import date

from sqlalchemy import select

from app.core.db import AsyncSessionLocal, init_models
from app.models.org import ClassRoom, School, User
from app.models.rbac import Permission, PermissionAssignment, Role, RolePermission
from app.models.school_ops import ClassScheduleEntry, SchoolShift

PERM_KEY = "manage_school_ops"
PERM_TITLE = "مدیریت عملیات مدرسه"


async def _ensure_permission(db) -> Permission:
    perm = (
        await db.execute(select(Permission).where(Permission.key == PERM_KEY))
    ).scalar_one_or_none()
    if perm is None:
        perm = Permission(key=PERM_KEY, title_fa=PERM_TITLE)
        db.add(perm)
        await db.flush()
        print(f"+ permission {PERM_KEY}")

    # نقش‌هایی که این مجوز را برمی‌دارند
    roles = (
        await db.execute(select(Role).where(Role.key.in_(("school_admin", "district_admin", "deputy"))))
    ).scalars().all()
    for role in roles:
        exists = (
            await db.execute(
                select(RolePermission.id).where(
                    RolePermission.role_id == role.id, RolePermission.permission_id == perm.id
                )
            )
        ).first()
        if exists is None:
            db.add(RolePermission(role_id=role.id, permission_id=perm.id))
            print(f"+ role_permission {role.key}")

    # تخصیص کاربران نمونه (scope مدرسه/ناحیه مطابق seed)
    for username, scope_type, scope_ref in (
        ("schooladmin", "school", lambda s: s.id == 1),
        ("districtadmin", "district", None),
    ):
        user = (
            await db.execute(select(User).where(User.username == username))
        ).scalar_one_or_none()
        if user is None:
            continue
        role = (
            await db.execute(
                select(Role).where(Role.key == ("school_admin" if username == "schooladmin" else "district_admin"))
            )
        ).scalar_one_or_none()
        if role is None:
            continue
        # scope: مدرسه اول / اولین ناحیه (مطابق seed)
        if scope_type == "school":
            scope_id = 1
        else:
            from app.models.org import District

            first_district = (await db.execute(select(District).order_by(District.id))).scalars().first()
            if first_district is None:
                continue
            scope_id = first_district.id
        exists = (
            await db.execute(
                select(PermissionAssignment.id).where(
                    PermissionAssignment.user_id == user.id,
                    PermissionAssignment.role_id == role.id,
                    PermissionAssignment.permission_id == perm.id,
                    PermissionAssignment.scope_type == scope_type,
                    PermissionAssignment.scope_id == scope_id,
                )
            )
        ).first()
        if exists is None:
            db.add(
                PermissionAssignment(
                    user_id=user.id,
                    role_id=role.id,
                    permission_id=perm.id,
                    scope_type=scope_type,
                    scope_id=scope_id,
                    is_active=True,
                )
            )
            print(f"+ permission_assignment {username} ({scope_type}={scope_id})")
    await db.flush()
    return perm


async def _ensure_shifts(db) -> None:
    schools = (await db.execute(select(School).order_by(School.id))).scalars().all()
    plan = {
        1: [("شیفت صبح", "08:00", "15:00")],
        2: [("شیفت اول", "08:00", "12:00"), ("شیفت دوم", "12:00", "18:00")],
    }
    for school in schools:
        rows = plan.get(school.id)
        if rows is None:
            continue
        existing = (
            await db.execute(select(SchoolShift.id).where(SchoolShift.school_id == school.id))
        ).first()
        if existing is not None:
            continue
        for i, (name, start, end) in enumerate(rows):
            db.add(SchoolShift(school_id=school.id, name=name, start_time=start, end_time=end, order=i))
        print(f"+ shifts school={school.id} ({len(rows)})")
    await db.flush()


async def _ensure_schedule(db) -> None:
    teachers = {
        u.username: u.id
        for u in (
            await db.execute(select(User).where(User.username.in_(("teacher1", "teacher2"))))
        ).scalars().all()
    }
    classes = (await db.execute(select(ClassRoom).order_by(ClassRoom.id))).scalars().all()
    by_key = {(c.school_id, c.name): c.id for c in classes}
    cls_101 = by_key.get((1, "۱۰۱"))
    cls_102 = by_key.get((1, "۱۰۲"))
    cls_201 = by_key.get((2, "۲۰۱"))
    t1 = teachers.get("teacher1")
    t2 = teachers.get("teacher2")

    plan = []
    if cls_101 and t1:
        plan += [
            (cls_101, 1, 0, "08:00", "09:30", "math", t1),
            (cls_101, 1, 1, "08:00", "09:30", "math", t1),
            (cls_101, 1, 2, "08:00", "09:30", "math", t1),
            (cls_101, 1, 3, "10:00", "11:30", "math", t1),
            (cls_101, 1, 4, "10:00", "11:30", "math", t1),
        ]
    if cls_102 and t2:
        plan += [
            (cls_102, 1, 0, "11:00", "12:30", "math", t2),
            (cls_102, 1, 2, "11:00", "12:30", "math", t2),
            (cls_102, 1, 4, "13:00", "14:30", "math", t2),
        ]
    if cls_201:
        plan += [
            (cls_201, 2, 0, "08:00", "09:30", "math", None),
            (cls_201, 2, 2, "09:45", "11:15", "math", None),
        ]

    for class_id, school_id, day, start, end, subject, teacher_user_id in plan:
        exists = (
            await db.execute(
                select(ClassScheduleEntry.id).where(
                    ClassScheduleEntry.class_id == class_id,
                    ClassScheduleEntry.day == day,
                    ClassScheduleEntry.start_time == start,
                )
            )
        ).first()
        if exists is not None:
            continue
        db.add(
            ClassScheduleEntry(
                class_id=class_id,
                school_id=school_id,
                day=day,
                start_time=start,
                end_time=end,
                subject=subject,
                teacher_user_id=teacher_user_id,
            )
        )
        print(f"+ schedule class={class_id} day={day} {start}-{end}")
    await db.flush()


async def main() -> None:
    await init_models()  # جدول‌های جدید را می‌سازد
    async with AsyncSessionLocal() as db:
        await _ensure_permission(db)
        await _ensure_shifts(db)
        await _ensure_schedule(db)
        await db.commit()
    print("Migration OK")


if __name__ == "__main__":
    asyncio.run(main())
