"""سرویس عملیات روزانه مدرسه (پنل کامل مدیر مدرسه):

- شیفت‌های متغیر مدرسه (تک‌شیفت/دو شیفت با ساعت دلخواه مدیر)؛
- برنامه هفتگی هر کلاس با اعتبارسنجی کامل (تداخل کلاس، تداخل معلم بین
  کلاس‌ها، انطباق با شیفت، عضویت معلم در مدرسه)؛
- رکورد دانش‌آموزان با جایگاه کلاسی + جابه‌جایی بین کلاس‌ها (ظرفیت‌محور)؛
- فهرست کادر آموزشی با شیفتِ استخراج‌شده از همان برنامه (یک منبع حقیقت)؛
- کلاس‌ها و تخصیص معلم به کلاس.

«همه‌جا هماهنگ بماند»: دانش‌آموز و معلم همین ردیف‌ها را می‌خوانند
(app/services/school_ops.student_schedule / teacher_schedule)."""
from __future__ import annotations

import re

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.org import (
    ClassRoom,
    ClassTeacherAssignment,
    Employee,
    School,
    SchoolAssignment,
    StudentProfile,
    User,
)
from app.models.school_ops import ClassScheduleEntry, SchoolShift
from app.services.rbac_service import log_action

DAY_NAMES = ["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه"]
MAX_SHIFTS = 3

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _mins(t: str) -> int:
    m = _TIME_RE.match(t)
    if m is None:
        raise HTTPException(400, f"ساعت نامعتبر است ({t}) — قالب HH:MM")
    return int(m.group(1)) * 60 + int(m.group(2))


def _row_of(s: SchoolShift) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "start_time": s.start_time,
        "end_time": s.end_time,
        "order": s.order,
    }


async def list_shifts(db: AsyncSession, school_id: int) -> list[dict]:
    rows = (
        await db.execute(
            select(SchoolShift)
            .where(SchoolShift.school_id == school_id)
            .order_by(SchoolShift.order, SchoolShift.start_time)
        )
    ).scalars().all()
    return [_row_of(s) for s in rows]


async def set_shifts(db: AsyncSession, school_id: int, rows: list[dict], actor_user_id: int) -> dict:
    """جایگزینی کامل شیفت‌های مدرسه — ساعت‌ها با تأیید مدیر (پنل مدرسه §تنظیمات)."""
    if not (1 <= len(rows) <= MAX_SHIFTS):
        raise HTTPException(400, f"باید بین ۱ تا {fa_num(MAX_SHIFTS)} شیفت تعریف کنید")

    cleaned: list[dict] = []
    names: set[str] = set()
    for r in rows:
        name = (r.get("name") or "").strip()
        if not name:
            raise HTTPException(400, "نام شیفت الزامی است")
        if len(name) > 60:
            raise HTTPException(400, "نام شیفت حداکثر ۶۰ نویسه است")
        if name in names:
            raise HTTPException(400, "نام شیفت‌ها نباید تکراری باشد")
        names.add(name)
        start, end = r.get("start_time") or "", r.get("end_time") or ""
        s, e = _mins(start), _mins(end)
        if s >= e:
            raise HTTPException(400, f"در شیفت «{name}» ساعت پایان باید بعد از ساعت شروع باشد")
        cleaned.append({"name": name, "start_time": start, "end_time": end, "_s": s, "_e": e})

    cleaned.sort(key=lambda c: c["_s"])
    for a, b in zip(cleaned, cleaned[1:]):
        if b["_s"] < a["_e"]:
            raise HTTPException(
                400, f"شیفت‌های «{a['name']}» و «{b['name']}» روی هم می‌افتند"
            )

    # برنامه فعلی کلاس‌ها باید در شیفت‌های جدید بگنجد؛ وگرنه مدیر باید اول برنامه را اصلاح کند
    existing = (
        await db.execute(select(ClassScheduleEntry).where(ClassScheduleEntry.school_id == school_id))
    ).scalars().all()
    orphans = [
        e for e in existing
        if not any(c["_s"] <= _mins(e.start_time) and _mins(e.end_time) <= c["_e"] for c in cleaned)
    ]
    if orphans:
        classes = {e.class_id for e in orphans}
        raise HTTPException(
            400,
            f"{len(orphans)} جلسه از برنامه هفتگی {len(classes)} کلاس خارج از شیفت‌های جدید است؛ "
            "اول برنامه هفتگی را اصلاح کنید",
        )

    await db.execute(delete(SchoolShift).where(SchoolShift.school_id == school_id))
    for i, c in enumerate(cleaned):
        db.add(
            SchoolShift(
                school_id=school_id,
                name=c["name"],
                start_time=c["start_time"],
                end_time=c["end_time"],
                order=i,
            )
        )
    await db.flush()
    await log_action(
        db,
        actor_user_id=actor_user_id,
        action="school_shifts_updated",
        entity_type="school",
        entity_id=school_id,
        detail=f"count={len(cleaned)}",
    )
    return {"shifts": await list_shifts(db, school_id)}


def fa_num(n: int) -> str:
    """عدد فارسی ساده برای پیام‌های خطای کاربرپسند."""
    return str(n).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


async def _teacher_is_school_staff(db: AsyncSession, school_id: int, teacher_user_id: int) -> bool:
    """معلم باید به این مدرسه تعلق داشته باشد (تخصیص مدرسه‌ای فعال یا
    تخصیص فعال به یکی از کلاس‌های همین مدرسه)."""
    user = await db.get(User, teacher_user_id)
    if user is None or user.system_role != "teacher":
        return False
    emp_ids = select(Employee.id).where(Employee.user_id == teacher_user_id)
    sa = (
        await db.execute(
            select(SchoolAssignment.id)
            .where(
                SchoolAssignment.employee_id.in_(emp_ids),
                SchoolAssignment.school_id == school_id,
                SchoolAssignment.status == "active",
            )
            .limit(1)
        )
    ).first()
    if sa is not None:
        return True
    cta = (
        await db.execute(
            select(ClassTeacherAssignment.id)
            .join(ClassRoom, ClassTeacherAssignment.class_id == ClassRoom.id)
            .where(
                ClassRoom.school_id == school_id,
                ClassTeacherAssignment.teacher_user_id == teacher_user_id,
                ClassTeacherAssignment.status == "active",
            )
            .limit(1)
        )
    ).first()
    return cta is not None


async def _validate_entries(
    db: AsyncSession, school_id: int, class_id: int, rows: list[dict]
) -> list[dict]:
    """اعتبارسنجی یک برنامه هفتگی کامل (replace) پیش از ثبت."""
    if len(rows) > 200:
        raise HTTPException(400, "برنامه هفتگی یک کلاس حداکثر ۲۰۰ جلسه است")

    shifts = (
        await db.execute(
            select(SchoolShift)
            .where(SchoolShift.school_id == school_id)
            .order_by(SchoolShift.order)
        )
    ).scalars().all()
    windows = [(_mins(s.start_time), _mins(s.end_time), s.name) for s in shifts]

    cleaned: list[dict] = []
    for r in rows:
        day = r.get("day")
        if not isinstance(day, int) or not (0 <= day <= 6):
            raise HTTPException(400, "روز هفته باید بین ۰ (شنبه) تا ۶ (جمعه) باشد")
        start, end = r.get("start_time") or "", r.get("end_time") or ""
        s, e = _mins(start), _mins(end)
        if s >= e:
            raise HTTPException(400, "ساعت پایان هر جلسه باید بعد از ساعت شروع آن باشد")
        subject = (r.get("subject") or "").strip()
        if not subject:
            raise HTTPException(400, "درس هر جلسه الزامی است")
        if len(subject) > 50:
            raise HTTPException(400, "نام درس حداکثر ۵۰ نویسه است")

        teacher_id = r.get("teacher_user_id")
        if teacher_id is not None:
            if not isinstance(teacher_id, int):
                raise HTTPException(400, "شناسه معلم نامعتبر است")
            if not await _teacher_is_school_staff(db, school_id, teacher_id):
                raise HTTPException(400, "این کاربر معلمِ فعال این مدرسه نیست")

        if windows and not any(ws <= s and e <= we for ws, we, _ in windows):
            names = "، ".join(w[2] for w in windows)
            raise HTTPException(
                400, f"بازه {start}–{end} خارج از شیفت‌های مدرسه ({names}) است"
            )
        cleaned.append(
            {
                "day": day,
                "start_time": start,
                "end_time": end,
                "subject": subject,
                "teacher_user_id": teacher_id,
                "_s": s,
                "_e": e,
            }
        )

    # تداخل داخل کلاس
    for day in range(7):
        day_rows = sorted([c for c in cleaned if c["day"] == day], key=lambda c: c["_s"])
        for a, b in zip(day_rows, day_rows[1:]):
            if b["_s"] < a["_e"]:
                raise HTTPException(
                    400,
                    f"در {DAY_NAMES[day]} برنامه «{a['start_time']}–{a['end_time']}» و "
                    f"«{b['start_time']}–{b['end_time']}» روی هم می‌افتند",
                )

    # تداخل معلم بین کلاس‌ها (معلم همزمان فقط در یک کلاس)
    by_teacher: dict[int, list[dict]] = {}
    for c in cleaned:
        if c["teacher_user_id"] is not None:
            by_teacher.setdefault(c["teacher_user_id"], []).append(c)
    for teacher_id, mine in by_teacher.items():
        others = (
            await db.execute(
                select(ClassScheduleEntry).where(
                    ClassScheduleEntry.teacher_user_id == teacher_id,
                    ClassScheduleEntry.class_id != class_id,
                )
            )
        ).scalars().all()
        class_names = {
            c.id: c.name
            for c in (
                await db.execute(
                    select(ClassRoom).where(
                        ClassRoom.id.in_({e.class_id for e in others} or {0})
                    )
                )
            ).scalars().all()
        }
        for c in mine:
            for o in others:
                if o.day == c["day"] and c["_s"] < _mins(o.end_time) and _mins(o.start_time) < c["_e"]:
                    raise HTTPException(
                        400,
                        f"معلم در {DAY_NAMES[c['day']]} ساعت "
                        f"{max(c['start_time'], o.start_time)}–{min(c['end_time'], o.end_time)} "
                        f"در کلاس {class_names.get(o.class_id, o.class_id)} درس دارد",
                    )
    return [{k: v for k, v in c.items() if not k.startswith("_")} for c in cleaned]


async def get_class_schedule(db: AsyncSession, class_id: int) -> dict:
    cls = await db.get(ClassRoom, class_id)
    if cls is None:
        raise HTTPException(404, "کلاس یافت نشد")
    entries = (
        await db.execute(
            select(ClassScheduleEntry)
            .where(ClassScheduleEntry.class_id == class_id)
            .order_by(ClassScheduleEntry.day, ClassScheduleEntry.start_time)
        )
    ).scalars().all()
    teacher_ids = {e.teacher_user_id for e in entries if e.teacher_user_id is not None}
    teachers = {
        u.id: u.full_name
        for u in (
            await db.execute(select(User).where(User.id.in_(teacher_ids or {0})))
        ).scalars().all()
    }
    return {
        "class_id": cls.id,
        "class_name": cls.name,
        "grade": cls.grade,
        "school_id": cls.school_id,
        "shifts": await list_shifts(db, cls.school_id),
        "entries": [
            {
                "id": e.id,
                "day": e.day,
                "day_name": DAY_NAMES[e.day],
                "start_time": e.start_time,
                "end_time": e.end_time,
                "subject": e.subject,
                "teacher_user_id": e.teacher_user_id,
                "teacher_name": teachers.get(e.teacher_user_id) if e.teacher_user_id else None,
            }
            for e in entries
        ],
    }


async def replace_class_schedule(
    db: AsyncSession, school_id: int, class_id: int, rows: list[dict], actor_user_id: int
) -> dict:
    """جایگزینی کامل برنامه هفتگی یک کلاس + رویداد ممیزی."""
    cleaned = await _validate_entries(db, school_id, class_id, rows)
    await db.execute(delete(ClassScheduleEntry).where(ClassScheduleEntry.class_id == class_id))
    for c in cleaned:
        db.add(ClassScheduleEntry(school_id=school_id, class_id=class_id, **c))
    await db.flush()
    await log_action(
        db,
        actor_user_id=actor_user_id,
        action="class_schedule_updated",
        entity_type="class",
        entity_id=class_id,
        detail=f"entries={len(cleaned)}",
    )
    return await get_class_schedule(db, class_id)


async def get_school_schedule(db: AsyncSession, school_id: int) -> dict:
    """برنامه هفتگی همه کلاس‌های مدرسه + شیفت‌ها — نمای یکپارچه مدیر."""
    classes = (
        await db.execute(
            select(ClassRoom).where(ClassRoom.school_id == school_id).order_by(ClassRoom.id)
        )
    ).scalars().all()
    out = []
    for cls in classes:
        out.append(await get_class_schedule(db, cls.id))
    return {
        "school_id": school_id,
        "shifts": await list_shifts(db, school_id),
        "classes": out,
    }


async def roster(db: AsyncSession, school_id: int) -> dict:
    """همه دانش‌آموزان مدرسه با جایگاه کلاسی + بدون کلاس + کلاس‌ها."""
    classes = (
        await db.execute(
            select(ClassRoom).where(ClassRoom.school_id == school_id).order_by(ClassRoom.id)
        )
    ).scalars().all()
    profiles = (
        await db.execute(
            select(StudentProfile)
            .where(StudentProfile.school_id == school_id)
            .order_by(StudentProfile.class_id, StudentProfile.user_id)
        )
    ).scalars().all()
    user_ids = [p.user_id for p in profiles]
    users = {
        u.id: u
        for u in (
            (await db.execute(select(User).where(User.id.in_(user_ids or {0})))).scalars().all()
            if user_ids
            else []
        )
    }

    def student_row(p: StudentProfile) -> dict:
        u = users.get(p.user_id)
        return {
            "user_id": p.user_id,
            "full_name": u.full_name if u else None,
            "username": u.username if u else None,
            "grade": p.grade,
            "status": p.status,
            "class_id": p.class_id,
        }

    by_class: dict[int | None, list[dict]] = {}
    for p in profiles:
        by_class.setdefault(p.class_id, []).append(student_row(p))

    return {
        "school_id": school_id,
        "total_students": len(profiles),
        "unassigned_students": by_class.get(None, []),
        "classes": [
            {
                "id": c.id,
                "name": c.name,
                "grade": c.grade,
                "capacity": c.capacity,
                "students_count": len(by_class.get(c.id, [])),
                "students": by_class.get(c.id, []),
            }
            for c in classes
        ],
    }


async def move_student(
    db: AsyncSession, school_id: int, user_id: int, class_id: int | None, actor_user_id: int
) -> dict:
    """جابه‌جایی دانش‌آموز بین کلاس‌ها (یا بدون کلاس) — تغییرِ واحدِ داده که
    همه پنل‌ها فوراً از همان می‌خوانند."""
    profile = (
        await db.execute(select(StudentProfile).where(StudentProfile.user_id == user_id))
    ).scalar_one_or_none()
    if profile is None or profile.school_id != school_id:
        raise HTTPException(404, "دانش‌آموز در این مدرسه یافت نشد")

    if class_id is not None:
        target = await db.get(ClassRoom, class_id)
        if target is None or target.school_id != school_id:
            raise HTTPException(400, "کلاس مقصد به این مدرسه تعلق ندارد")
        count = (
            await db.execute(
                select(StudentProfile.id)
                .where(StudentProfile.class_id == class_id, StudentProfile.user_id != user_id)
            )
        ).scalars().all()
        if len(count) >= target.capacity:
            raise HTTPException(409, f"ظرفیت کلاس {target.name} تکمیل است")

    if profile.class_id == class_id:
        return {"ok": True, "class_id": class_id, "unchanged": True}

    old_class = profile.class_id
    profile.class_id = class_id
    await db.flush()
    await log_action(
        db,
        actor_user_id=actor_user_id,
        action="student_class_moved",
        entity_type="student_profile",
        entity_id=profile.id,
        detail=f"user={user_id} {old_class} -> {class_id}",
    )
    return {"ok": True, "class_id": class_id, "unchanged": False}


# ------------------------- کلاس‌ها و کادر آموزشی -------------------------


async def create_class(
    db: AsyncSession,
    school_id: int,
    *,
    name: str,
    grade: str,
    track: str | None,
    capacity: int,
    actor_user_id: int,
) -> dict:
    from app.services import admission as admission_svc

    name = (name or "").strip()
    if not name:
        raise HTTPException(400, "نام کلاس الزامی است")
    if len(name) > 60:
        raise HTTPException(400, "نام کلاس حداکثر ۶۰ نویسه است")
    if not admission_svc.grade_ok(grade):
        raise HTTPException(400, "پایه تحصیلی نامعتبر است")
    if capacity < 1 or capacity > 100:
        raise HTTPException(400, "ظرفیت کلاس باید بین ۱ تا ۱۰۰ باشد")

    dup = (
        await db.execute(
            select(ClassRoom.id).where(ClassRoom.school_id == school_id, ClassRoom.name == name)
        )
    ).first()
    if dup is not None:
        raise HTTPException(409, "کلاسی با این نام در مدرسه وجود دارد")

    cls = ClassRoom(
        school_id=school_id, grade=grade, track=track, name=name, capacity=capacity
    )
    db.add(cls)
    await db.flush()
    await log_action(
        db,
        actor_user_id=actor_user_id,
        action="class_created",
        entity_type="class",
        entity_id=cls.id,
        detail=f"school={school_id} name={name}",
    )
    return {"id": cls.id, "name": cls.name, "grade": cls.grade, "capacity": cls.capacity}


async def update_class(
    db: AsyncSession, class_id: int, *, name: str | None, capacity: int | None, actor_user_id: int
) -> dict:
    cls = await db.get(ClassRoom, class_id)
    if cls is None:
        raise HTTPException(404, "کلاس یافت نشد")
    if name is not None:
        name = name.strip()
        if not name:
            raise HTTPException(400, "نام کلاس نمی‌تواند خالی باشد")
        dup = (
            await db.execute(
                select(ClassRoom.id).where(
                    ClassRoom.school_id == cls.school_id,
                    ClassRoom.name == name,
                    ClassRoom.id != class_id,
                )
            )
        ).first()
        if dup is not None:
            raise HTTPException(409, "کلاسی با این نام در مدرسه وجود دارد")
        cls.name = name
    if capacity is not None:
        if capacity < 1 or capacity > 100:
            raise HTTPException(400, "ظرفیت کلاس باید بین ۱ تا ۱۰۰ باشد")
        enrolled = (
            await db.execute(
                select(StudentProfile.id).where(StudentProfile.class_id == class_id)
            )
        ).scalars().all()
        if capacity < len(enrolled):
            raise HTTPException(409, f"ظرفیت کمتر از {len(enrolled)} دانش‌آموز ثبت‌شده نیست")
        cls.capacity = capacity
    await db.flush()
    await log_action(
        db,
        actor_user_id=actor_user_id,
        action="class_updated",
        entity_type="class",
        entity_id=class_id,
        detail=f"name={cls.name} capacity={cls.capacity}",
    )
    return {"id": cls.id, "name": cls.name, "grade": cls.grade, "capacity": cls.capacity}


async def assign_teacher(
    db: AsyncSession, class_id: int, teacher_user_id: int, subject: str, actor_user_id: int
) -> dict:
    cls = await db.get(ClassRoom, class_id)
    if cls is None:
        raise HTTPException(404, "کلاس یافت نشد")
    subject = (subject or "").strip()
    if not subject:
        raise HTTPException(400, "درس الزامی است")
    if not await _teacher_is_school_staff(db, cls.school_id, teacher_user_id):
        raise HTTPException(400, "این کاربر معلمِ فعال این مدرسه نیست")

    dup = (
        await db.execute(
            select(ClassTeacherAssignment.id).where(
                ClassTeacherAssignment.class_id == class_id,
                ClassTeacherAssignment.teacher_user_id == teacher_user_id,
                ClassTeacherAssignment.subject == subject,
                ClassTeacherAssignment.status == "active",
            )
        )
    ).first()
    if dup is not None:
        raise HTTPException(409, "این معلم همین درس را به این کلاس تدریس می‌کند")

    from datetime import date

    a = ClassTeacherAssignment(
        class_id=class_id,
        teacher_user_id=teacher_user_id,
        subject=subject,
        start_date=date.today(),
        status="active",
    )
    db.add(a)
    await db.flush()
    await log_action(
        db,
        actor_user_id=actor_user_id,
        action="class_teacher_assigned",
        entity_type="class",
        entity_id=class_id,
        detail=f"teacher={teacher_user_id} subject={subject}",
    )
    return {"id": a.id, "class_id": class_id, "teacher_user_id": teacher_user_id, "subject": subject}


async def unassign_teacher(db: AsyncSession, class_id: int, assignment_id: int, actor_user_id: int) -> dict:
    a = await db.get(ClassTeacherAssignment, assignment_id)
    if a is None or a.class_id != class_id:
        raise HTTPException(404, "تخصیص معلم یافت نشد")
    # صداقت داده: تا وقتی برنامه هفتگی این کلاس جلسه‌ای با این معلم دارد،
    # تخصیص بسته نمی‌شود (اول برنامه را خالی کنید).
    entry = (
        await db.execute(
            select(ClassScheduleEntry.id).where(
                ClassScheduleEntry.class_id == class_id,
                ClassScheduleEntry.teacher_user_id == a.teacher_user_id,
            )
            .limit(1)
        )
    ).first()
    if entry is not None:
        raise HTTPException(
            409, "این معلم در برنامه هفتگی این کلاس جلسه دارد؛ اول برنامه را ویرایش کنید"
        )
    from datetime import date

    a.status = "inactive"
    a.end_date = date.today()
    await db.flush()
    await log_action(
        db,
        actor_user_id=actor_user_id,
        action="class_teacher_unassigned",
        entity_type="class",
        entity_id=class_id,
        detail=f"teacher={a.teacher_user_id} assignment={assignment_id}",
    )
    return {"ok": True, "id": assignment_id}


async def staff(db: AsyncSession, school_id: int) -> dict:
    """کادر آموزشی مدرسه: کلاس‌ها/درس‌ها + شیفت و بار هفتگی استخراج‌شده از
    برنامه هفتگی (یک منبع حقیقت)."""
    # معلمان از دو مسیر: تخصیص مدرسه‌ای فعالِ «معلمی» + تخصیص فعال کلاسی
    # (مدیر/معاونِ صرفاً اداری در فهرست کادر آموزشی نمی‌آید)
    emp_user = {
        e.id: e.user_id
        for e in (await db.execute(select(Employee))).scalars().all()
    }
    sa_rows = (
        await db.execute(
            select(SchoolAssignment).where(
                SchoolAssignment.school_id == school_id,
                SchoolAssignment.status == "active",
            )
        )
    ).scalars().all()
    teacher_ids = {
        emp_user[e.employee_id]
        for e in sa_rows
        if e.employee_id in emp_user and e.role == "teacher"
    }

    class_rows = (
        await db.execute(
            select(ClassTeacherAssignment, ClassRoom.name)
            .join(ClassRoom, ClassTeacherAssignment.class_id == ClassRoom.id)
            .where(
                ClassRoom.school_id == school_id,
                ClassTeacherAssignment.status == "active",
            )
        )
    ).all()
    for a, _ in class_rows:
        teacher_ids.add(a.teacher_user_id)

    users = {
        u.id: u
        for u in (
            await db.execute(select(User).where(User.id.in_(teacher_ids or {0})))
        ).scalars().all()
    }
    entries = (
        await db.execute(
            select(ClassScheduleEntry).where(
                ClassScheduleEntry.school_id == school_id,
                ClassScheduleEntry.teacher_user_id.in_(teacher_ids or {0}),
            )
        )
    ).scalars().all()
    shifts = (
        await db.execute(
            select(SchoolShift)
            .where(SchoolShift.school_id == school_id)
            .order_by(SchoolShift.order)
        )
    ).scalars().all()
    windows = [(_mins(s.start_time), _mins(s.end_time), s.name) for s in shifts]

    per_teacher_classes: dict[int, set[str]] = {}
    for a, cname in class_rows:
        per_teacher_classes.setdefault(a.teacher_user_id, set()).add(cname)
    subjects_by_teacher: dict[int, set[str]] = {}
    for a, _ in class_rows:
        subjects_by_teacher.setdefault(a.teacher_user_id, set()).add(a.subject)
    for e in sa_rows:
        uid = emp_user.get(e.employee_id)
        if uid is not None and e.subject:
            subjects_by_teacher.setdefault(uid, set()).add(e.subject)

    by_teacher: dict[int, list[ClassScheduleEntry]] = {}
    for e in entries:
        by_teacher.setdefault(e.teacher_user_id, []).append(e)

    out = []
    for uid in sorted(teacher_ids):
        rows = by_teacher.get(uid, [])
        my_shifts: set[str] = set()
        minutes = 0
        days: set[int] = set()
        for e in rows:
            s, t = _mins(e.start_time), _mins(e.end_time)
            minutes += t - s
            days.add(e.day)
            for ws, we, wname in windows:
                if ws <= s and t <= we:
                    my_shifts.add(wname)
        out.append(
            {
                "user_id": uid,
                "full_name": users[uid].full_name if uid in users else None,
                "classes": sorted(per_teacher_classes.get(uid, set())),
                "subjects": sorted(subjects_by_teacher.get(uid, set())),
                "shifts": sorted(my_shifts),
                "has_schedule": bool(rows),
                "weekly_sessions": len(rows),
                "weekly_hours": round(minutes / 60, 1),
                "days": sorted(days),
                "day_names": [DAY_NAMES[d] for d in sorted(days)],
            }
        )
    return {
        "school_id": school_id,
        "shifts": [_row_of(s) for s in shifts],
        "teachers": out,
    }


# ------------------------- دید هماهنگ دانش‌آموز / معلم -------------------------


async def student_schedule(db: AsyncSession, user_id: int) -> dict:
    """برنامه هفتگی کلاسِ دانش‌آموز — همان ردیف‌هایی که مدیر ثبت کرده است."""
    profile = (
        await db.execute(select(StudentProfile).where(StudentProfile.user_id == user_id))
    ).scalar_one_or_none()
    if profile is None:
        return {"class_id": None, "class_name": None, "shifts": [], "entries": []}
    base = {
        "class_id": profile.class_id,
        "class_name": None,
        "school_id": profile.school_id,
        "shifts": await list_shifts(db, profile.school_id),
        "entries": [],
    }
    if profile.class_id is None:
        return base
    data = await get_class_schedule(db, profile.class_id)
    base["class_name"] = data["class_name"]
    base["entries"] = data["entries"]
    return base


async def teacher_schedule(db: AsyncSession, user_id: int) -> dict:
    """برنامه هفتگی همه کلاس‌های معلم + شیفتِ استخراج‌شده از همان برنامه."""
    entries = (
        await db.execute(
            select(ClassScheduleEntry, ClassRoom.name, School.name)
            .join(ClassRoom, ClassScheduleEntry.class_id == ClassRoom.id)
            .join(School, ClassScheduleEntry.school_id == School.id)
            .where(ClassScheduleEntry.teacher_user_id == user_id)
            .order_by(ClassScheduleEntry.day, ClassScheduleEntry.start_time)
        )
    ).all()

    schools: dict[int, dict] = {}
    for e, class_name, school_name in entries:
        bucket = schools.setdefault(
            e.school_id,
            {"school_id": e.school_id, "school_name": school_name, "entries": [], "_mins": 0},
        )
        bucket["entries"].append(
            {
                "id": e.id,
                "day": e.day,
                "day_name": DAY_NAMES[e.day],
                "start_time": e.start_time,
                "end_time": e.end_time,
                "subject": e.subject,
                "class_id": e.class_id,
                "class_name": class_name,
            }
        )
        bucket["_mins"] += _mins(e.end_time) - _mins(e.start_time)

    out = []
    for sid, b in schools.items():
        windows = (
            await db.execute(
                select(SchoolShift)
                .where(SchoolShift.school_id == sid)
                .order_by(SchoolShift.order)
            )
        ).scalars().all()
        my_shifts = set()
        for e in b["entries"]:
            s, t = _mins(e["start_time"]), _mins(e["end_time"])
            for w in windows:
                if _mins(w.start_time) <= s and t <= _mins(w.end_time):
                    my_shifts.add(w.name)
        out.append(
            {
                "school_id": sid,
                "school_name": b["school_name"],
                "shifts": [_row_of(w) for w in windows],
                "my_shifts": sorted(my_shifts),
                "weekly_hours": round(b["_mins"] / 60, 1),
                "entries": b["entries"],
            }
        )
    return {"schools": out}
