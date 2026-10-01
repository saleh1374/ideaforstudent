"""School / province / national boards (roadmap phase 5 «بردها»).

اصل سراسری سند: نمایش تجمیعی با نام مستعار و حداقل جمعیت ۱۰ نفر — زیر
حد نصاب، عدد اصلاً نمایش داده نمی‌شود (suppressed)، نه تخمین و نه رنگ."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.org import ClassRoom, Province, School, StudentProfile
from app.models.slm import StudentTopicState
from app.services.slm import status_of


def pseudonym(prefix: str, entity_id: int) -> str:
    """نام مستعار پایدار: کلاس «ک-۳»، مدرسه «م-۷» — بدون افشای نام واقعی."""
    # ارقام فارسی برای خوانایی رابط
    digits = str(entity_id).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
    return f"{prefix}-{digits}"


async def _states_of(db: AsyncSession, student_ids: list[int]) -> list[StudentTopicState]:
    if not student_ids:
        return []
    return list(
        (
            await db.execute(
                select(StudentTopicState).where(StudentTopicState.student_user_id.in_(student_ids))
            )
        ).scalars()
    )


def _aggregate(states: list[StudentTopicState], min_group: int) -> dict:
    """تجمیع با قاعده حداقل جمعیت: زیر min_group → همه عددها None + suppressed."""
    students = {s.student_user_id for s in states if s.evidence_count >= 3}
    if len(students) < min_group:
        return {
            "students_with_data": len(students),
            "avg_mastery": None,
            "avg_retention": None,
            "weak_count": None,
            "status_counts": None,
            "suppressed": True,
        }
    with_data = [s for s in states if s.evidence_count >= 3]
    counts: dict[str, int] = {}
    for s in with_data:
        k = status_of(s.effective_mastery, s.evidence_count)
        counts[k] = counts.get(k, 0) + 1
    return {
        "students_with_data": len(students),
        "avg_mastery": round(sum(s.effective_mastery for s in with_data) / len(with_data), 1) if with_data else None,
        "avg_retention": round(sum(s.retention for s in with_data) / len(with_data), 3) if with_data else None,
        "weak_count": sum(1 for s in with_data if s.effective_mastery < get_settings().threshold_consolidating),
        "status_counts": counts,
        "suppressed": False,
    }


async def school_board(db: AsyncSession, school_id: int) -> dict:
    """برد مدرسه: کلاس‌ها با نام مستعار + تجمیع تسلط."""
    s = get_settings()
    classes = (await db.execute(select(ClassRoom).where(ClassRoom.school_id == school_id))).scalars().all()
    rows = []
    for c in classes:
        ids = [
            p.user_id
            for p in (await db.execute(select(StudentProfile).where(StudentProfile.class_id == c.id))).scalars()
        ]
        agg = _aggregate(await _states_of(db, ids), s.min_group_size)
        rows.append({"key": pseudonym("ک", c.id), "kind": "class", **agg})
    # تجمیع کل مدرسه
    all_ids = [
        p.user_id
        for p in (await db.execute(select(StudentProfile).where(StudentProfile.school_id == school_id))).scalars()
    ]
    school_agg = _aggregate(await _states_of(db, all_ids), s.min_group_size)
    rows.sort(key=lambda r: (r["suppressed"], r["avg_mastery"] if r["avg_mastery"] is not None else 999))
    return {
        "scope": "school",
        "school_id": school_id,
        "min_group": s.min_group_size,
        "note_fa": f"اعداد فقط با حداقل {s.min_group_size} دانش‌آموز دارای داده نمایش داده می‌شوند؛ نام‌ها مستعار‌اند.",
        "total": school_agg,
        "rows": rows,
    }


async def province_board(db: AsyncSession, province_id: int) -> dict:
    """برد استان: مدارس با نام مستعار."""
    s = get_settings()
    schools = (await db.execute(select(School).where(School.province_id == province_id))).scalars().all()
    rows = []
    for sc in schools:
        ids = [
            p.user_id
            for p in (await db.execute(select(StudentProfile).where(StudentProfile.school_id == sc.id))).scalars()
        ]
        agg = _aggregate(await _states_of(db, ids), s.min_group_size)
        rows.append({"key": pseudonym("م", sc.id), "kind": "school", **agg})
    rows.sort(key=lambda r: (r["suppressed"], r["avg_mastery"] if r["avg_mastery"] is not None else 999))
    return {
        "scope": "province",
        "province_id": province_id,
        "min_group": s.min_group_size,
        "note_fa": f"مقایسه مدارس فقط با حداقل {s.min_group_size} دانش‌آموز دارای داده؛ نام مدارس مستعار است.",
        "rows": rows,
    }


async def national_board(db: AsyncSession) -> dict:
    """برد کشور: استان‌ها — نام مستعار + حداقل جمعیت."""
    s = get_settings()
    provinces = (await db.execute(select(Province))).scalars().all()
    # دانش‌آموزان هر استان از طریق مدرسه
    schools = (await db.execute(select(School))).scalars().all()
    prov_of_school = {sc.id: sc.province_id for sc in schools}
    school_ids = [sc.id for sc in schools]
    profiles = (
        await db.execute(select(StudentProfile).where(StudentProfile.school_id.in_(school_ids)))
    ).scalars() if school_ids else []
    by_prov: dict[int, list[int]] = {}
    for p in profiles:
        pid = prov_of_school.get(p.school_id)
        if pid is not None:
            by_prov.setdefault(pid, []).append(p.user_id)
    rows = []
    for prov in provinces:
        agg = _aggregate(await _states_of(db, by_prov.get(prov.id, [])), s.min_group_size)
        rows.append({"key": pseudonym("استان", prov.id), "kind": "province", **agg})
    rows.sort(key=lambda r: (r["suppressed"], r["avg_mastery"] if r["avg_mastery"] is not None else 999))
    return {
        "scope": "national",
        "min_group": s.min_group_size,
        "note_fa": f"رتبه‌بندی استان‌ها با نام مستعار و حداقل جمعیت {s.min_group_size} نفر.",
        "rows": rows,
    }
