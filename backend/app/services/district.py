"""District admin service (district spec §1, §2, §4, §12): تجمیع مدارس و
ناحیه از همان هسته SLM با رعایت قاعده حداقل جمعیت ۱۰ + شمارش‌های سازمانی.
اصل سند: «پنل ناحیه داده جدیدی نمی‌سازد» — فقط فیلتر و تجمیع روی داده موجود."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.employment import EmploymentRequest
from app.models.catalog import Topic
from app.models.org import (
    ClassRoom,
    District,
    Employee,
    Employment,
    School,
    SchoolAssignment,
    StudentProfile,
    User,
)
from app.models.slm import StudentTopicState
from app.services.rbac_service import active_assignments
from app.services.slm import status_of


async def caller_district_id(db: AsyncSession, user_id: int) -> int | None:
    """ناحیه تماس‌گیرنده از روی حوزه مجوزهای فعال او (District Scope —
    district spec §1: نقش بدون محدوده معنا ندارد)."""
    rows = await active_assignments(db, user_id)
    districts = sorted({pa.scope_id for pa, _ in rows if pa.scope_type == "district"})
    return districts[0] if districts else None


async def district_schools(db: AsyncSession, district_id: int) -> list[School]:
    return list(
        (
            await db.execute(select(School).where(School.district_id == district_id).order_by(School.id))
        ).scalars()
    )


async def school_summary(db: AsyncSession, school: School) -> dict:
    """تجمیع یک مدرسه با قاعده حریم خصوصی: زیر حداقل جمعیت ۱۰ دانش‌آموز
    دارای داده، هیچ عددی نمایش داده نمی‌شود (suppressed)."""
    s = get_settings()
    profiles = (
        await db.execute(select(StudentProfile).where(StudentProfile.school_id == school.id))
    ).scalars().all()
    student_ids = [p.user_id for p in profiles]
    states = (
        list(
            (
                await db.execute(
                    select(StudentTopicState).where(StudentTopicState.student_user_id.in_(student_ids))
                )
            ).scalars()
        )
        if student_ids
        else []
    )
    with_data = [st for st in states if st.evidence_count >= s.evidence_min_for_status]
    students_with_data = {st.student_user_id for st in with_data}
    suppressed = len(students_with_data) < s.min_group_size

    counts: dict[str, int] = {}
    for st in with_data:
        key = status_of(st.effective_mastery, st.evidence_count)
        counts[key] = counts.get(key, 0) + 1

    return {
        "students_count": len(student_ids),
        "students_with_data": len(students_with_data),
        "avg_mastery": (
            None
            if suppressed or not with_data
            else round(sum(st.effective_mastery for st in with_data) / len(with_data), 1)
        ),
        "weak_count": (
            None
            if suppressed
            else sum(1 for st in with_data if st.effective_mastery < s.threshold_consolidating)
        ),
        "status_counts": None if suppressed else counts,
        "suppressed": suppressed,
        "min_group": s.min_group_size,
    }


async def school_row(db: AsyncSession, school: School) -> dict:
    summary = await school_summary(db, school)
    principal = await active_principal(db, school.id)
    return {
        "id": school.id,
        "name": school.name,
        "school_code": school.school_code,
        "school_type": school.school_type,
        "ownership_type": school.ownership_type,
        "status": school.status,
        "principal": (
            {"user_id": principal.id, "full_name": principal.full_name} if principal else None
        ),
        **summary,
    }


async def overview(db: AsyncSession, district_id: int) -> dict:
    """نمای کلان ناحیه (district spec §2 + §3): وضعیت آموزشی تجمیعی،
    شمارش‌های سازمانی و ضعیف‌ترین مباحث درون ناحیه."""
    s = get_settings()
    district = await db.get(District, district_id)
    schools = await district_schools(db, district_id)
    school_ids = [sc.id for sc in schools]

    profiles = (
        list(
            (await db.execute(select(StudentProfile).where(StudentProfile.school_id.in_(school_ids)))).scalars()
        )
        if school_ids
        else []
    )
    student_ids = [p.user_id for p in profiles]
    states = (
        list(
            (
                await db.execute(
                    select(StudentTopicState).where(StudentTopicState.student_user_id.in_(student_ids))
                )
            ).scalars()
        )
        if student_ids
        else []
    )
    with_data = [st for st in states if st.evidence_count >= s.evidence_min_for_status]
    students_with_data = {st.student_user_id for st in with_data}
    suppressed = len(students_with_data) < s.min_group_size

    counts: dict[str, int] = {}
    for st in with_data:
        key = status_of(st.effective_mastery, st.evidence_count)
        counts[key] = counts.get(key, 0) + 1
    avg_mastery = (
        None if suppressed or not with_data else round(sum(st.effective_mastery for st in with_data) / len(with_data), 1)
    )

    classes_count = (
        (await db.execute(select(ClassRoom.id).where(ClassRoom.school_id.in_(school_ids)))).all()
        if school_ids
        else []
    )
    teacher_employees = (
        {
            row[0]
            for row in (
                await db.execute(
                    select(SchoolAssignment.employee_id).where(
                        SchoolAssignment.school_id.in_(school_ids),
                        SchoolAssignment.role == "teacher",
                        SchoolAssignment.status == "active",
                    )
                )
            ).all()
        }
        if school_ids
        else set()
    )
    teachers_count = 0
    if teacher_employees:
        user_ids = {
            row[0]
            for row in (
                await db.execute(select(Employee.user_id).where(Employee.id.in_(teacher_employees)))
            ).all()
        }
        teachers_count = len(user_ids)
    pending = (
        (
            await db.execute(
                select(EmploymentRequest.id).where(
                    EmploymentRequest.school_id.in_(school_ids),
                    EmploymentRequest.status == "pending",
                )
            )
        ).all()
        if school_ids
        else []
    )

    # ضعیف‌ترین مباحث ناحیه — فقط مباحثی که بالای حداقل جمعیت‌اند
    titles = {t.id: t.title_fa for t in (await db.execute(select(Topic))).scalars()}
    by_topic: dict[int, list[StudentTopicState]] = {}
    for st in states:
        by_topic.setdefault(st.topic_id, []).append(st)
    topic_rows = []
    for topic_id, topic_states in by_topic.items():
        topic_with_data = [st for st in topic_states if st.evidence_count >= s.evidence_min_for_status]
        topic_students = {st.student_user_id for st in topic_with_data}
        if len(topic_students) < s.min_group_size or not topic_with_data:
            continue
        topic_rows.append(
            {
                "topic_id": topic_id,
                "title": titles.get(topic_id, f"#{topic_id}"),
                "students_count": len(topic_students),
                "avg_mastery": round(
                    sum(st.effective_mastery for st in topic_with_data) / len(topic_with_data), 1
                ),
            }
        )
    topic_rows.sort(key=lambda row: row["avg_mastery"])

    return {
        "district": {"id": district.id, "name": district.name} if district else {"id": district_id, "name": None},
        "schools_count": len(schools),
        "students_count": len(profiles),
        "classes_count": len(classes_count),
        "teachers_count": teachers_count,
        "pending_employment_requests": len(pending),
        "educational": {
            "avg_mastery": avg_mastery,
            "suppressed": suppressed,
            "min_group": s.min_group_size,
            "status_counts": None if suppressed else counts,
            "needs_intervention": None if suppressed else counts.get("critical", 0) + counts.get("weak", 0),
        },
        "worst_topics": topic_rows[:5],
        "note_fa": (
            f"اعداد تجمیعی ناحیه فقط با حداقل {s.min_group_size} دانش‌آموز دارای داده نمایش داده می‌شود؛ "
            "جزئیات خصوصی دانش‌آموزان نیازمند مجوز جداگانه است (district spec §35)."
        ),
    }


async def district_staff(db: AsyncSession, district_id: int) -> list[dict]:
    """کارکنان اداری ناحیه: Employment(organization='district') + پروفایل هویت."""
    employments = (
        await db.execute(
            select(Employment).where(
                Employment.organization == "district",
                Employment.district_id == district_id,
            )
        )
    ).scalars().all()
    out: list[dict] = []
    for employment in employments:
        employee = await db.get(Employee, employment.employee_id)
        user = await db.get(User, employee.user_id) if employee else None
        if user is None:
            continue
        out.append(
            {
                "user_id": user.id,
                "username": user.username,
                "full_name": user.full_name,
                "system_role": user.system_role,
                "is_active": user.is_active,
                "employment": {
                    "type": employment.employment_type,
                    "organization": employment.organization,
                    "status": employment.status,
                    "start_date": employment.start_date.isoformat() if employment.start_date else None,
                },
            }
        )
    return out


async def find_district_staff_user(db: AsyncSession, district_id: int) -> User | None:
    """اولین کاربر فعال این ناحیه — مثلاً برای نمایش مدیر ناحیه در پاسخ‌ها."""
    staff = await district_staff(db, district_id)
    for row in staff:
        user = await db.get(User, row["user_id"])
        if user is not None and user.is_active:
            return user
    return None


async def active_principal(db: AsyncSession, school_id: int) -> User | None:
    """مدیر (principal) فعال مدرسه — برای نمایش در فهرست مدارس."""
    row = (
        await db.execute(
            select(SchoolAssignment)
            .where(
                SchoolAssignment.school_id == school_id,
                SchoolAssignment.role == "principal",
                SchoolAssignment.status == "active",
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    employee = await db.get(Employee, row.employee_id)
    if employee is None:
        return None
    return await db.get(User, employee.user_id)
