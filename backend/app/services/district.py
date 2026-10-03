"""District admin service (district spec §1–§9, §12, §19, §23, §29–§32):
تجمیع مدارس و ناحیه از همان هسته SLM با رعایت قاعده حداقل جمعیت ۱۰ + شمارش‌های
سازمانی + مقایسه/رشد مدارس، سلامت شش‌محوری، مرکز توجه، تحلیل خطای ناحیه و
پیش‌نویس گزارش ناحیه.
اصل سند: «پنل ناحیه داده جدیدی نمی‌سازد» — فقط فیلتر و تجمیع روی داده موجود."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.assessment import Exam, ExamAttempt
from app.models.employment import EmploymentRequest
from app.models.catalog import Book, Chapter, Prerequisite, Topic
from app.models.district_exams import (
    DistrictExam,
    DistrictIntervention,
    DistrictInterventionSchool,
)
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
from app.models.slm import ErrorRecord, Evidence, PlanTask, StudentTopicState
from app.services.rbac_service import active_assignments
from app.services.slm import status_of

# ---- ثابت‌های مرکز توجه و تحلیل ناحیه (district spec ضمیمه الف — نقطه شروع،
# کالیبراسیون نهایی در پایلوت و روی داده واقعی انجام می‌شود) ----
STAGNATION_GROWTH_MAX = 1.0        # §11 پرچم «رکود»: رشد تسط زیر این مقدار
DIVERGENCE_DELTA = 10.0            # §11/§9 پرچم «واگرایی» از میانگین ناحیه
PREREQ_WEAK_RATIO = 0.5            # §11 «ضعف گسترده پیش‌نیاز»
CRITICAL_DROP_RATIO = 0.5          # §29 هشدار بحرانی: سهم دانش‌آموزان نیازمند مداخله
POSITIVE_GROWTH = 10.0             # §29 هشدار مثبت: رشد قابل توجه
POSITIVE_INTERVENTION_DELTA = 5.0  # §29 تجربه موفق قابل تکثیر
COMMON_PROBLEM_MIN_SCHOOLS = 2     # §8 حداقل مدرسه برای «مشکل مشترک ناحیه»
COMMON_PROBLEM_WEAK_RATIO = 0.6    # §8 بیش از ۶۰٪ دانش‌آموزان یک پایه
PERIOD_GOAL_MASTERY = 70.0         # §6 «سطح ورودی ← وضعیت فعلی ← میزان رشد»

ERROR_CAUSE_FA = {
    "conceptual": "مفهومی",
    "prerequisite": "پیش‌نیاز",
    "calculation": "محاسباتی",
    "careless": "بی‌دقتی",
    "time_management": "مدیریت زمان",
    "misread": "درک نادرست صورت مسئله",
    "guess": "سایر",
}

SEVERITY_RANK = {"critical": 0, "attention": 1, "forming": 2, "normal": 3, "positive": 4}
SEVERITY_FA = {
    "critical": "بحرانی",
    "attention": "نیازمند توجه",
    "forming": "در حال شکل‌گیری",
    "normal": "عادی",
    "positive": "مثبت",
}

_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa_num(value) -> str:
    """ارقام فارسی برای برچسب‌های رابط کاربری."""
    return str(value).translate(_FA_DIGITS)


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


# =====================================================================
# §5/§6 مقایسه و رشد مدارس · §2/§3 روندها و شش محور · §9/§11/§29/§30
# مرکز توجه · §23 تحلیل خطای ناحیه · §31 گزارش ناحیه
# =====================================================================


async def _topic_maps(db: AsyncSession):
    """عنوان مبحث + درسِ هر مبحث + مجموعه پیش‌نیازها (سه کوئری، بدون N+1)."""
    topics = {t.id: t for t in (await db.execute(select(Topic))).scalars()}
    chapters = {c.id: c.book_id for c in (await db.execute(select(Chapter))).scalars()}
    books = {b.id: b.subject for b in (await db.execute(select(Book))).scalars()}
    subject_of = {tid: books.get(chapters.get(t.chapter_id)) for tid, t in topics.items()}
    prereq_ids = {row[0] for row in (await db.execute(select(Prerequisite.prereq_topic_id))).all()}
    return topics, subject_of, prereq_ids


async def district_bundle(db: AsyncSession, district_id: int, grade: str | None = None, subject: str | None = None) -> dict:
    """همه‌ی داده‌های لازم تحلیل ناحیه در چند کوئری — پایه‌ی مقایسه، رشد،
    مرکز توجه، خطاها و گزارش (بدون N+1 روی دانش‌آموز)."""
    s = get_settings()
    schools = await district_schools(db, district_id)
    school_ids = [sc.id for sc in schools]
    profiles = (
        list(
            (await db.execute(select(StudentProfile).where(StudentProfile.school_id.in_(school_ids)))).scalars()
        )
        if school_ids
        else []
    )
    if grade is not None:
        profiles = [p for p in profiles if p.grade == grade]
    student_ids = [p.user_id for p in profiles]

    topics, subject_of, prereq_ids = await _topic_maps(db)
    topic_ids: set[int] | None = None
    if subject:
        topic_ids = {tid for tid, sub in subject_of.items() if sub == subject}

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
    if topic_ids is not None:
        states = [st for st in states if st.topic_id in topic_ids]

    errors = (
        list(
            (await db.execute(select(ErrorRecord).where(ErrorRecord.student_user_id.in_(student_ids)))).scalars()
        )
        if student_ids
        else []
    )
    tasks = (
        list((await db.execute(select(PlanTask).where(PlanTask.student_user_id.in_(student_ids)))).scalars())
        if student_ids
        else []
    )
    attempts: list[tuple[ExamAttempt, Exam]] = []
    if student_ids:
        attempts = list(
            (
                await db.execute(
                    select(ExamAttempt, Exam)
                    .join(Exam, Exam.id == ExamAttempt.exam_id)
                    .where(
                        ExamAttempt.student_user_id.in_(student_ids),
                        ExamAttempt.submitted_at.is_not(None),
                    )
                )
            ).all()
        )
    return {
        "settings": s,
        "schools": schools,
        "profiles": profiles,
        "states": states,
        "errors": errors,
        "tasks": tasks,
        "attempts": attempts,
        "topics": topics,
        "subject_of": subject_of,
        "prereq_ids": prereq_ids,
        "grade": grade,
        "subject": subject,
    }


def _growth_of(states: list[StudentTopicState]) -> dict:
    """سطح ورودی ← وضعیت فعلی ← میزان رشد + سری ماهانه تسط (§6).

    سطح اولیه از نخستین نقطه‌ی تاریخچه‌ی SLM هر دانش‌آموز می‌آید؛ اگر
    تاریخچه‌ای نباشد خودِ تسط فعلی مبنا قرار می‌گیرد (رشد صفر)."""
    entries: list[float] = []
    currents: list[float] = []
    retentions: list[float] = []
    buckets: dict[str, list[float]] = {}
    for st in states:
        points: list[tuple[str, float]] = []
        for h in st.history or []:
            at, e = h.get("at"), h.get("e")
            if at and e is not None:
                points.append((str(at)[:7], float(e)))
        if points:
            entries.append(points[0][1])
            for month, e in points:
                buckets.setdefault(month, []).append(e)
        else:
            entries.append(float(st.effective_mastery))
            buckets.setdefault("now", []).append(float(st.effective_mastery))
        currents.append(float(st.effective_mastery))
        retentions.append(float(st.retention or 0.0))

    if not currents:
        return {"entry": None, "current": None, "growth": None, "avg_retention": None, "series": []}

    entry = round(sum(entries) / len(entries), 1)
    current = round(sum(currents) / len(currents), 1)
    series = []
    for month in sorted(buckets):
        vals = buckets[month]
        label = "کنون" if month == "now" else month.replace("-", "/")
        series.append(
            {"label": fa_num(label), "value": round(sum(vals) / len(vals), 1), "points": len(vals)}
        )
    return {
        "entry": entry,
        "current": current,
        "growth": round(current - entry, 1),
        "avg_retention": round(sum(retentions) / len(retentions), 3),
        "series": series,
    }


def _exam_series(bundle: dict, ids: set[int]) -> tuple[list[dict], float | None]:
    """سری درصد آزمون‌های تصحیح‌شده (به ترتیب آزمون) + رشد نسبت به آزمون قبلی (§2)."""
    by_exam: dict[int, list[float]] = {}
    order: list[tuple[datetime, int]] = []
    for attempt, exam in bundle["attempts"]:
        if attempt.student_user_id not in ids or attempt.percent is None:
            continue
        by_exam.setdefault(exam.id, []).append(float(attempt.percent))
        order.append((attempt.submitted_at or datetime.min, exam.id))
    if not by_exam:
        return [], None
    ordered = [exam_id for _, exam_id in sorted(set(order))]
    titles = {exam.id: exam.title_fa for _, exam in bundle["attempts"]}
    series = [
        {"label": titles.get(eid, f"آزمون #{eid}"), "value": round(sum(by_exam[eid]) / len(by_exam[eid]), 1)}
        for eid in ordered
    ]
    delta = None
    if len(series) >= 2:
        delta = round(series[-1]["value"] - series[-2]["value"], 1)
    return series, delta


def _percentile_rows(bundle: dict, student_ids: set[int]) -> tuple[int, int]:
    """(تعداد دانش‌آموز دارای میانگین، تعداد نیازمند مداخله)."""
    s = bundle["settings"]
    by_student: dict[int, list[float]] = {}
    for st in bundle["states"]:
        if st.student_user_id in student_ids and st.evidence_count >= s.evidence_min_for_status:
            by_student.setdefault(st.student_user_id, []).append(float(st.effective_mastery))
    need = 0
    for vals in by_student.values():
        if (sum(vals) / len(vals)) < s.threshold_consolidating:
            need += 1
    return len(by_student), need


# ------------------------- §5 مقایسه مدارس -------------------------


async def school_comparison(db: AsyncSession, district_id: int, grade: str | None = None, subject: str | None = None) -> dict:
    """مقایسه مدارس روی شاخص‌های §5 در سه گام «سطح ورودی ← وضعیت فعلی ←
    میزان رشد»؛ زیر حداقل جمعیت هیچ عدد آموزشی نمایش داده نمی‌شود."""
    s = get_settings()
    bundle = await district_bundle(db, district_id, grade=grade, subject=subject)
    rows: list[dict] = []
    for school in bundle["schools"]:
        profiles = [p for p in bundle["profiles"] if p.school_id == school.id]
        ids = {p.user_id for p in profiles}
        states = [st for st in bundle["states"] if st.student_user_id in ids]
        with_data = [st for st in states if st.evidence_count >= s.evidence_min_for_status]
        students_with_data = {st.student_user_id for st in with_data}
        suppressed = len(students_with_data) < s.min_group_size
        g = _growth_of(with_data)

        errors = [e for e in bundle["errors"] if e.student_user_id in ids]
        cause_counts: dict[str, int] = {}
        for e in errors:
            cause_counts[e.cause] = cause_counts.get(e.cause, 0) + 1
        total_errors = len(errors)

        tasks = [t for t in bundle["tasks"] if t.student_user_id in ids]
        done = sum(1 for t in tasks if t.status == "done")

        percents = [
            float(a.percent)
            for a, _ex in bundle["attempts"]
            if a.student_user_id in ids and a.percent is not None
        ]
        with_avg, need = _percentile_rows(bundle, ids)

        def _or_none(value, allowed=True):
            return None if (suppressed or not allowed) else value

        rows.append(
            {
                "school_id": school.id,
                "name": school.name,
                "school_code": school.school_code,
                "school_type": school.school_type,
                "ownership_type": school.ownership_type,
                "status": school.status,
                "students_count": len(profiles),
                "students_with_data": len(students_with_data),
                "suppressed": suppressed,
                "min_group": s.min_group_size,
                "entry_mastery": _or_none(g["entry"]),
                "current_mastery": _or_none(g["current"]),
                "growth": _or_none(g["growth"]),
                "avg_retention": _or_none(g["avg_retention"]),
                "exam_avg": _or_none(round(sum(percents) / len(percents), 1) if percents else None, bool(percents)),
                "conceptual_error_pct": _or_none(
                    round(100.0 * cause_counts.get("conceptual", 0) / total_errors, 1) if total_errors else None,
                    bool(total_errors),
                ),
                "calculation_error_pct": _or_none(
                    round(100.0 * cause_counts.get("calculation", 0) / total_errors, 1) if total_errors else None,
                    bool(total_errors),
                ),
                "practice_completion_pct": _or_none(
                    round(100.0 * done / len(tasks), 1) if tasks else None, bool(tasks)
                ),
                "needs_intervention_pct": _or_none(
                    round(100.0 * need / with_avg, 1) if with_avg else None, bool(with_avg)
                ),
                "errors_total": _or_none(total_errors, bool(total_errors)),
            }
        )
    rows.sort(key=lambda r: (r["suppressed"], -(r["current_mastery"] or -1.0)))
    return {
        "district_id": district_id,
        "grade": grade,
        "subject": subject,
        "min_group": s.min_group_size,
        "stages": ["سطح ورودی", "وضعیت فعلی", "میزان رشد"],
        "goal_mastery": PERIOD_GOAL_MASTERY,
        "rows": rows,
        "note_fa": (
            "مقایسه در سه گام انجام می‌شود: سطح ورودی ← وضعیت فعلی ← میزان رشد. "
            "رتبه‌بندی ساده مدارس معیار اصلی نیست؛ مدرسه‌ای که دانش‌آموزان ورودی قوی‌تری "
            "دارد نمره خام بالاتری می‌گیرد (district spec §5)."
        ),
    }


# ------------------------- §6 تحلیل «رشد» مدارس -------------------------


async def school_growth(db: AsyncSession, district_id: int) -> dict:
    """وضعیت فعلی در برابر رشد + سری رشد در طول زمان (§6/§2) — با یادآوری
    صریح که «وضعیت فعلی و میزان رشد دو شاخص متفاوت‌اند»."""
    s = get_settings()
    bundle = await district_bundle(db, district_id)
    all_with_data = [st for st in bundle["states"] if st.evidence_count >= s.evidence_min_for_status]
    district_growth = _growth_of(all_with_data)

    rows: list[dict] = []
    for school in bundle["schools"]:
        profiles = [p for p in bundle["profiles"] if p.school_id == school.id]
        ids = {p.user_id for p in profiles}
        with_data = [
            st
            for st in bundle["states"]
            if st.student_user_id in ids and st.evidence_count >= s.evidence_min_for_status
        ]
        suppressed = len({st.student_user_id for st in with_data}) < s.min_group_size
        g = _growth_of(with_data)
        exam_series, exam_delta = _exam_series(bundle, ids)
        rows.append(
            {
                "school_id": school.id,
                "name": school.name,
                "suppressed": suppressed,
                "entry": None if suppressed else g["entry"],
                "current": None if suppressed else g["current"],
                "growth": None if suppressed else g["growth"],
                "series": [] if suppressed else g["series"],
                "exam_series": [] if suppressed else exam_series,
                "growth_vs_prev_exam": None if suppressed else exam_delta,
                "trend": (
                    None
                    if suppressed or g["growth"] is None
                    else ("up" if g["growth"] > STAGNATION_GROWTH_MAX else "flat" if g["growth"] >= -STAGNATION_GROWTH_MAX else "down")
                ),
            }
        )
    rows.sort(key=lambda r: (r["suppressed"], -(r["growth"] if r["growth"] is not None else -999)))
    return {
        "district_id": district_id,
        "min_group": s.min_group_size,
        "district": {
            "entry": district_growth["entry"],
            "current": district_growth["current"],
            "growth": district_growth["growth"],
            "series": district_growth["series"],
        },
        "rows": rows,
        "note_fa": (
            "وضعیت فعلی و میزان رشد دو شاخص متفاوت‌اند؛ مدرسه‌ای که امروز پایین‌تر است "
            "ممکن است رشد بسیار بیشتری ایجاد کرده باشد — همین نگاه تحلیل ناحیه را از "
            "«نمرهمحوری» دور می‌کند (district spec §6)."
        ),
    }


# ------------------------- §2 روندها -------------------------


def _band(value: float | None, good: float, medium: float) -> str:
    """طبقه‌بندی نرم یک شاخص برای نمایش رنگی (بدون ترکیب در عدد ساختگی)."""
    if value is None:
        return "unknown"
    if value >= good:
        return "good"
    if value >= medium:
        return "medium"
    return "weak"


async def trends(db: AsyncSession, district_id: int) -> dict:
    """روندهای داشبورد ناحیه (§2): رشد نسبت به آزمون/دوره قبلی، روند تسط و
    ماندگاری، مشارکت، تکمیل برنامه، مداخله‌ها و وضعیت آزمون‌ها."""
    s = get_settings()
    bundle = await district_bundle(db, district_id)
    with_data = [st for st in bundle["states"] if st.evidence_count >= s.evidence_min_for_status]
    students_with_data = {st.student_user_id for st in with_data}
    suppressed = len(students_with_data) < s.min_group_size
    g = _growth_of(with_data)

    # رشد نسبت به آزمون قبلی (میانگین Δ دانش‌آموزان دارای دو آزمون)
    per_student: dict[int, list[float]] = {}
    for attempt, _exam in bundle["attempts"]:
        if attempt.percent is not None:
            per_student.setdefault(attempt.student_user_id, []).append(float(attempt.percent))
    deltas = [vals[-1] - vals[-2] for vals in per_student.values() if len(vals) >= 2]
    exam_growth = round(sum(deltas) / len(deltas), 1) if deltas else None

    # روند تسط: سهم دانش‌آموزانی که آخرین تاریخچه‌شان بهتر از نقطه اولیه است
    improved = declined = 0
    for st in with_data:
        hist = st.history or []
        if len(hist) >= 2:
            first, last = float(hist[0].get("e") or 0.0), float(hist[-1].get("e") or 0.0)
            if last > first + 0.5:
                improved += 1
            elif last < first - 0.5:
                declined += 1
    mastery_trend_pct = (
        round(100.0 * improved / (improved + declined), 1) if (improved + declined) else None
    )

    # مشارکت: دانش‌آموزان دارای شاهد در ۱۴ روز اخیر
    cutoff = datetime.utcnow() - timedelta(days=14)
    active_ids = set(
        {
            row[0]
            for row in (
                await db.execute(
                    select(Evidence.student_user_id).where(
                        Evidence.student_user_id.in_([p.user_id for p in bundle["profiles"]]),
                        Evidence.occurred_at >= cutoff,
                    )
                )
            ).all()
        }
        if bundle["profiles"]
        else set()
    )
    engagement_pct = (
        round(100.0 * len(active_ids & students_with_data) / len(students_with_data), 1)
        if students_with_data
        else None
    )

    tasks = bundle["tasks"]
    done = sum(1 for t in tasks if t.status == "done")
    completion_pct = round(100.0 * done / len(tasks), 1) if tasks else None

    interventions = list(
        (
            await db.execute(
                select(DistrictIntervention).where(DistrictIntervention.district_id == district_id)
            )
        ).scalars()
    )
    measured = [iv for iv in interventions if iv.before_mastery is not None and iv.after_mastery is not None]
    effective = [iv for iv in measured if (iv.after_mastery or 0) - (iv.before_mastery or 0) > 0]
    intervention_pct = round(100.0 * len(effective) / len(measured), 1) if measured else None

    exams = list(
        (await db.execute(select(DistrictExam).where(DistrictExam.district_id == district_id))).scalars()
    )
    open_exams = sum(1 for e in exams if e.status in ("published", "graded"))
    closed_exams = sum(1 for e in exams if e.status == "closed")

    def _dir(value: float | None, eps: float = 0.5) -> str:
        if value is None:
            return "none"
        return "up" if value > eps else "down" if value < -eps else "flat"

    items = [
        {
            "key": "exam_growth",
            "title_fa": "رشد نسبت به آزمون قبلی",
            "value": exam_growth,
            "unit": "درصد",
            "direction": _dir(exam_growth),
            "band": _band(exam_growth, 5.0, 0.0),
            "note_fa": f"میانگین تغییر درصد {fa_num(len(deltas))} دانش‌آموز دارای دو آزمون.",
        },
        {
            "key": "period_growth",
            "title_fa": "رشد نسبت به دوره قبلی",
            "value": None if suppressed else g["growth"],
            "unit": "واحد تسط",
            "direction": "none" if suppressed else _dir(g["growth"]),
            "band": "unknown" if suppressed else _band(g["growth"], 5.0, 0.0),
            "note_fa": "تفاوت تسط فعلی با سطح ورودی دانش‌آموزان.",
        },
        {
            "key": "mastery_trend",
            "title_fa": "روند تسط",
            "value": None if suppressed else mastery_trend_pct,
            "unit": "٪ بهبود",
            "direction": "none" if mastery_trend_pct is None else "up" if mastery_trend_pct >= 50 else "down",
            "band": "unknown" if mastery_trend_pct is None else _band(mastery_trend_pct, 60.0, 40.0),
            "note_fa": f"{fa_num(improved)} دانش‌آموز بهبود و {fa_num(declined)} دانش‌آموز افت داشته‌اند.",
        },
        {
            "key": "retention_trend",
            "title_fa": "روند ماندگاری",
            "value": None if suppressed else g["avg_retention"],
            "unit": "نسبت",
            "direction": "none" if suppressed or g["avg_retention"] is None else "up" if g["avg_retention"] >= 0.75 else "down",
            "band": "unknown" if suppressed else _band(g["avg_retention"], 0.85, 0.6),
            "note_fa": "میانگین منحنی فراموشی (R) روی مباحث دارای داده.",
        },
        {
            "key": "engagement",
            "title_fa": "میزان مشارکت",
            "value": None if suppressed else engagement_pct,
            "unit": "٪",
            "direction": "none",
            "band": "unknown" if suppressed else _band(engagement_pct, 70.0, 40.0),
            "note_fa": "دانش‌آموزان دارای شاهد یادگیری در ۱۴ روز اخیر.",
        },
        {
            "key": "completion",
            "title_fa": "میزان تکمیل برنامه‌ها",
            "value": completion_pct,
            "unit": "٪",
            "direction": "none",
            "band": _band(completion_pct, 70.0, 40.0),
            "note_fa": f"{fa_num(done)} از {fa_num(len(tasks))} تکلیف انجام شده است.",
        },
        {
            "key": "intervention",
            "title_fa": "وضعیت مداخله‌ها",
            "value": intervention_pct,
            "unit": "٪ اثرگذار",
            "direction": "none",
            "band": _band(intervention_pct, 70.0, 40.0),
            "note_fa": (
                f"{fa_num(len(effective))} از {fa_num(len(measured))} مداخله اندازه‌گیری‌شده اثر مثبت داشته‌اند."
                if measured
                else "هنوز مداخله‌ای در دو مرحله «قبل/بعد» اندازه‌گیری نشده است."
            ),
        },
        {
            "key": "exams",
            "title_fa": "وضعیت آزمون‌ها",
            "value": open_exams,
            "unit": "آزمون فعال",
            "direction": "none",
            "band": "good" if open_exams else "unknown",
            "note_fa": f"{fa_num(open_exams)} آزمون منتشرشده/در حال تصحیح و {fa_num(closed_exams)} آزمون بسته.",
        },
    ]
    return {
        "district_id": district_id,
        "suppressed": suppressed,
        "min_group": s.min_group_size,
        "trends": items,
        "note_fa": (
            "روندها کنار اعداد خام نمایش داده می‌شوند؛ بدون حداقل جمعیت، روندهای مبتنی بر "
            "تسط سرکوب می‌شوند (district spec §2)."
        ),
    }


# ------------------------- §3 شش محور سلامت آموزشی -------------------------


async def health_axes(db: AsyncSession, district_id: int) -> dict:
    """سالمت آموزشی ناحیه از شش محور مستقل (§3) — هر محور جداگانه نمایش داده
    می‌شود؛ هیچ عدد ساختگی «سلامت ناحیه = ۷۸» ساخته نمی‌شود."""
    s = get_settings()
    bundle = await district_bundle(db, district_id)
    with_data = [st for st in bundle["states"] if st.evidence_count >= s.evidence_min_for_status]
    students_with_data = {st.student_user_id for st in with_data}
    suppressed = len(students_with_data) < s.min_group_size
    g = _growth_of(with_data)

    percents = [float(a.percent) for a, _ex in bundle["attempts"] if a.percent is not None]
    exam_avg = round(sum(percents) / len(percents), 1) if percents else None

    cutoff = datetime.utcnow() - timedelta(days=14)
    active_ids = set(
        {
            row[0]
            for row in (
                await db.execute(
                    select(Evidence.student_user_id).where(
                        Evidence.student_user_id.in_([p.user_id for p in bundle["profiles"]]),
                        Evidence.occurred_at >= cutoff,
                    )
                )
            ).all()
        }
        if bundle["profiles"]
        else set()
    )
    engagement = (
        round(100.0 * len(active_ids & students_with_data) / len(students_with_data), 1)
        if students_with_data
        else None
    )

    interventions = list(
        (
            await db.execute(
                select(DistrictIntervention).where(DistrictIntervention.district_id == district_id)
            )
        ).scalars()
    )
    measured = [iv for iv in interventions if iv.before_mastery is not None and iv.after_mastery is not None]
    effective = [iv for iv in measured if (iv.after_mastery or 0) - (iv.before_mastery or 0) > 0]
    intervention_pct = round(100.0 * len(effective) / len(measured), 1) if measured else None

    def axis(key, title, question, value, unit, band, detail):
        return {
            "key": key,
            "title_fa": title,
            "question_fa": question,
            "value": None if suppressed and value is not None else value,
            "unit": unit,
            "band": "unknown" if suppressed else band,
            "suppressed": suppressed,
            "detail_fa": detail,
        }

    axes = [
        axis(
            "learning",
            "یادگیری",
            "آیا یادگیری واقعی در حال رشد است؟",
            g["growth"],
            "واحد تسط",
            _band(g["growth"], 5.0, 0.0),
            "تفاوت تسط فعلی با سطح ورودی دانش‌آموزان دارای داده.",
        ),
        axis(
            "mastery",
            "تسط",
            "دانش‌آموزان چه میزان از مهارت‌های مورد انتظار را مسلط شده‌اند؟",
            g["current"],
            "٪",
            _band(g["current"], s.threshold_mastered, s.threshold_consolidating),
            f"میانگین تسط مؤثر روی مباحث دارای حداقل {fa_num(s.evidence_min_for_status)} شاهد.",
        ),
        axis(
            "retention",
            "ماندگاری",
            "آیا مطالب پس از گذشت زمان در ذهن مانده‌اند؟",
            g["avg_retention"],
            "نسبت",
            _band(g["avg_retention"], 0.85, 0.6),
            "میانگین منحنی فراموشی (R) در همان مباحث.",
        ),
        axis(
            "assessment",
            "سنجش",
            "آزمون‌ها درباره وضعیت یادگیری چه می‌گویند؟",
            exam_avg,
            "٪",
            _band(exam_avg, 80.0, 60.0),
            f"میانگین درصد {fa_num(len(percents))} نتیجه تصحیح‌شده در ناحیه.",
        ),
        axis(
            "engagement",
            "مشارکت",
            "دانش‌آموزان چقدر در برنامه شرکت می‌کنند؟",
            engagement,
            "٪",
            _band(engagement, 70.0, 40.0),
            "سهم دانش‌آموزان دارای شاهد یادگیری در ۱۴ روز اخیر.",
        ),
        axis(
            "intervention",
            "مداخله",
            "مداخلات آموزشی چقدر انجام شده و چقدر اثر داشته‌اند؟",
            intervention_pct,
            "٪ اثرگذار",
            _band(intervention_pct, 70.0, 40.0),
            (
                f"{fa_num(len(effective))} از {fa_num(len(measured))} مداخله اندازه‌گیری‌شده اثر مثبت داشته است."
                if measured
                else f"{fa_num(len(interventions))} مداخله ثبت شده و هنوز اندازه‌گیری «بعد» ندارد."
            ),
        ),
    ]
    return {
        "district_id": district_id,
        "axes": axes,
        "suppressed": suppressed,
        "min_group": s.min_group_size,
        "note_fa": (
            "شش محور جداگانه بررسی می‌شوند و در یک عدد ساختگی خلاصه نمی‌شوند؛ چنین عددی "
            "واقعیت را پنهان می‌کند (district spec §3)."
        ),
    }


# ------------------------- §9/§11/§29/§30 مرکز توجه -------------------------


async def attention_center(db: AsyncSession, district_id: int) -> dict:
    """مرکز توجه ناحیه: رتبه‌بندی مدارس/کلاس‌های نیازمند اقدام با پرچم‌های
    §11 + مشکلات مشترک §8 + هشدارهای §29 + کشف الگوی غیرعادی §30."""
    s = get_settings()
    bundle = await district_bundle(db, district_id)
    with_data = [st for st in bundle["states"] if st.evidence_count >= s.evidence_min_for_status]
    district_growth = _growth_of(with_data)["growth"]

    profile_by_student = {p.user_id: p for p in bundle["profiles"]}
    prereq_ids = bundle["prereq_ids"]

    interventions = list(
        (
            await db.execute(
                select(DistrictIntervention).where(DistrictIntervention.district_id == district_id)
            )
        ).scalars()
    )
    iv_by_school: dict[int, list[DistrictIntervention]] = {}
    if interventions:
        links = (
            (
                await db.execute(
                    select(DistrictInterventionSchool).where(
                        DistrictInterventionSchool.intervention_id.in_([iv.id for iv in interventions])
                    )
                )
            )
            .scalars()
            .all()
        )
        iv_map = {iv.id: iv for iv in interventions}
        for link in links:
            iv = iv_map.get(link.intervention_id)
            if iv is not None:
                iv_by_school.setdefault(link.school_id, []).append(iv)

    def states_of(ids: set[int]) -> list[StudentTopicState]:
        return [
            st
            for st in with_data
            if st.student_user_id in ids
        ]

    def flags_for(ids: set[int], growth: float | None, suppressed: bool, iv_rows: list[DistrictIntervention]) -> list[dict]:
        if suppressed:
            return []
        flags: list[dict] = []
        sts = states_of(ids)
        by_student: dict[int, list[StudentTopicState]] = {}
        for st in sts:
            by_student.setdefault(st.student_user_id, []).append(st)
        weak_students = sum(
            1
            for rows in by_student.values()
            if (sum(r.effective_mastery for r in rows) / len(rows)) < s.threshold_consolidating
        )
        weak_ratio = weak_students / len(by_student) if by_student else 0.0
        if weak_ratio >= CRITICAL_DROP_RATIO:
            flags.append(
                {
                    "code": "critical_drop",
                    "severity": "critical",
                    "title_fa": "افت قابل توجه تسط",
                    "detail_fa": f"{fa_num(round(weak_ratio * 100))}٪ دانش‌آموزان زیر آستانه تثبیت‌اند.",
                }
            )
        if growth is not None and growth <= STAGNATION_GROWTH_MAX:
            flags.append(
                {
                    "code": "stagnation",
                    "severity": "attention",
                    "title_fa": "رکود رشد",
                    "detail_fa": f"رشد تسط {fa_num(growth)} واحد بوده است (کمتر از {fa_num(STAGNATION_GROWTH_MAX)} واحد).",
                }
            )
        prereq_states = [st for st in sts if st.topic_id in prereq_ids]
        if prereq_states:
            weak_prereq = sum(
                1 for st in prereq_states if status_of(st.effective_mastery, st.evidence_count) in ("weak", "critical")
            )
            ratio = weak_prereq / len(prereq_states)
            if ratio > PREREQ_WEAK_RATIO:
                flags.append(
                    {
                        "code": "prereq_weak",
                        "severity": "forming",
                        "title_fa": "ضعف گسترده پیش‌نیاز",
                        "detail_fa": f"{fa_num(round(ratio * 100))}٪ مباحث پیش‌نیاز در وضعیت ضعیف/بحرانی‌اند.",
                    }
                )
        if growth is not None and district_growth is not None and abs(growth - district_growth) >= DIVERGENCE_DELTA:
            flags.append(
                {
                    "code": "divergence",
                    "severity": "attention",
                    "title_fa": "واگرایی از کلاس‌های مشابه ناحیه",
                    "detail_fa": (
                        f"فاصله رشد ({fa_num(growth)}) با میانگین ناحیه ({fa_num(district_growth)}) "
                        f"{fa_num(round(abs(growth - district_growth)))} واحد است — پرچم مدیریتی، نه حکم درباره کیفیت معلم."
                    ),
                }
            )
        positive = False
        for iv in iv_rows:
            if iv.before_mastery is None or iv.after_mastery is None:
                continue
            delta = (iv.after_mastery or 0) - (iv.before_mastery or 0)
            if delta <= 0:
                flags.append(
                    {
                        "code": "intervention_ineffective",
                        "severity": "attention",
                        "title_fa": "مداخله بی‌اثر",
                        "detail_fa": f"مداخله «{iv.title_fa}» بعد از اجرا {fa_num(round(delta, 1))} واحد تغییر نداشته است.",
                    }
                )
            elif delta >= POSITIVE_INTERVENTION_DELTA:
                positive = True
                flags.append(
                    {
                        "code": "intervention_works",
                        "severity": "positive",
                        "title_fa": "تجربه موفق قابل تکثیر",
                        "detail_fa": f"مداخله «{iv.title_fa}» {fa_num(round(delta, 1))} واحد بهبود داشته است.",
                    }
                )
        if growth is not None and growth >= POSITIVE_GROWTH:
            positive = True
            flags.append(
                {
                    "code": "strong_growth",
                    "severity": "positive",
                    "title_fa": "رشد قابل توجه",
                    "detail_fa": f"رشد تسط {fa_num(growth)} واحد ثبت شده است.",
                }
            )
        _ = positive
        return flags

    def severity_of(flags: list[dict]) -> str:
        sev = {f["severity"] for f in flags}
        for key in ("critical", "attention", "forming"):
            if key in sev:
                return key
        return "positive" if flags else "normal"

    def score_of(flags: list[dict], weak_hint: float = 0.0) -> float:
        weights = {"critical": 4.0, "attention": 3.0, "forming": 2.0, "positive": 0.0}
        return round(sum(weights.get(f["severity"], 0.0) for f in flags) + weak_hint, 2)

    # ---- مدارس ----
    school_rows: list[dict] = []
    for school in bundle["schools"]:
        profiles = [p for p in bundle["profiles"] if p.school_id == school.id]
        ids = {p.user_id for p in profiles}
        students_with_data = {st.student_user_id for st in states_of(ids)}
        suppressed = len(students_with_data) < s.min_group_size
        g = _growth_of(states_of(ids))
        with_avg, need = _percentile_rows(bundle, ids)
        weak_hint = (need / with_avg) if with_avg else 0.0
        flags = flags_for(ids, g["growth"], suppressed, iv_by_school.get(school.id, []))
        severity = severity_of(flags)
        school_rows.append(
            {
                "kind": "school",
                "id": school.id,
                "name": school.name,
                "school_code": school.school_code,
                "students_count": len(profiles),
                "students_with_data": len(students_with_data),
                "suppressed": suppressed,
                "growth": None if suppressed else g["growth"],
                "current_mastery": None if suppressed else g["current"],
                "needs_intervention_pct": None if suppressed or not with_avg else round(100.0 * need / with_avg, 1),
                "flags": flags,
                "severity": severity,
                "severity_fa": SEVERITY_FA[severity],
                "score": score_of(flags, 0.0 if suppressed else weak_hint),
            }
        )
    school_rows.sort(key=lambda r: (SEVERITY_RANK[r["severity"]], -r["score"], r["name"]))

    # ---- کلاس‌ها ----
    class_rows: list[dict] = []
    class_ids = [c.id for c in (await db.execute(select(ClassRoom).where(ClassRoom.school_id.in_([sc.id for sc in bundle["schools"]])))).scalars()] if bundle["schools"] else []
    classes = (
        (await db.execute(select(ClassRoom).where(ClassRoom.id.in_(class_ids)))).scalars() if class_ids else []
    )
    school_name = {sc.id: sc.name for sc in bundle["schools"]}
    for cls in classes:
        ids = {p.user_id for p in bundle["profiles"] if p.class_id == cls.id}
        students_with_data = {st.student_user_id for st in states_of(ids)}
        suppressed = len(students_with_data) < s.min_group_size
        g = _growth_of(states_of(ids))
        flags = flags_for(ids, g["growth"], suppressed, iv_by_school.get(cls.school_id, []))
        severity = severity_of(flags)
        class_rows.append(
            {
                "kind": "class",
                "id": cls.id,
                "name": f"{cls.name} — {school_name.get(cls.school_id, '')}",
                "school_id": cls.school_id,
                "grade": cls.grade,
                "students_count": len(ids),
                "students_with_data": len(students_with_data),
                "suppressed": suppressed,
                "growth": None if suppressed else g["growth"],
                "current_mastery": None if suppressed else g["current"],
                "flags": flags,
                "severity": severity,
                "severity_fa": SEVERITY_FA[severity],
                "score": score_of(flags),
            }
        )
    class_rows.sort(key=lambda r: (SEVERITY_RANK[r["severity"]], -r["score"], r["name"]))

    # ---- مشکلات مشترک کل ناحیه (§8) ----
    by_topic: dict[int, list[StudentTopicState]] = {}
    for st in with_data:
        by_topic.setdefault(st.topic_id, []).append(st)
    errors_by_topic: dict[int, list[ErrorRecord]] = {}
    for e in bundle["errors"]:
        errors_by_topic.setdefault(e.topic_id, []).append(e)
    prereq_titles: dict[int, list[str]] = {}
    for row in (await db.execute(select(Prerequisite))).scalars().all():
        prereq_titles.setdefault(row.topic_id, []).append(row.prereq_topic_id)

    problems: list[dict] = []
    for topic_id, sts in by_topic.items():
        students = {st.student_user_id for st in sts}
        if len(students) < s.min_group_size:
            continue
        weak_students = {
            st.student_user_id
            for st in sts
            if status_of(st.effective_mastery, st.evidence_count) in ("weak", "critical")
        }
        ratio = len(weak_students) / len(students)
        schools_hit = {
            profile_by_student[uid].school_id for uid in weak_students if uid in profile_by_student
        }
        classes_hit = {
            profile_by_student[uid].class_id for uid in weak_students if uid in profile_by_student
        }
        if ratio < COMMON_PROBLEM_WEAK_RATIO or len(schools_hit) < COMMON_PROBLEM_MIN_SCHOOLS:
            continue
        topic_errors = errors_by_topic.get(topic_id, [])
        cause_counts: dict[str, int] = {}
        for e in topic_errors:
            cause_counts[e.cause] = cause_counts.get(e.cause, 0) + 1
        dominant = max(cause_counts, key=cause_counts.get) if cause_counts else None
        prereq_ids_here = prereq_titles.get(topic_id, [])
        titles = bundle["topics"]
        problems.append(
            {
                "topic_id": topic_id,
                "title": titles[topic_id].title_fa if topic_id in titles else f"#{topic_id}",
                "weak_students": len(weak_students),
                "students_count": len(students),
                "weak_ratio": round(ratio * 100, 1),
                "schools": sorted(schools_hit),
                "schools_count": len(schools_hit),
                "classes_count": len({c for c in classes_hit if c is not None}),
                "dominant_error": dominant,
                "dominant_error_fa": ERROR_CAUSE_FA.get(dominant, dominant),
                "prerequisites": [
                    titles[pid].title_fa for pid in prereq_ids_here if pid in titles
                ],
                "avg_mastery": round(sum(st.effective_mastery for st in sts) / len(sts), 1),
            }
        )
    problems.sort(key=lambda p: (-p["schools_count"], -p["weak_ratio"]))

    # ---- هشدارها (§29) ----
    alerts: list[dict] = []
    for row in school_rows:
        for flag in row["flags"]:
            if flag["severity"] == "positive":
                continue
            alerts.append(
                {
                    "level": flag["severity"],
                    "level_fa": SEVERITY_FA[flag["severity"]],
                    "title_fa": f"{row['name']} — {flag['title_fa']}",
                    "message_fa": flag["detail_fa"],
                    "school_id": row["id"],
                }
            )
    for p in problems:
        alerts.append(
            {
                "level": "forming",
                "level_fa": SEVERITY_FA["forming"],
                "title_fa": f"ضعف مشترک در «{p['title']}»",
                "message_fa": (
                    f"{fa_num(p['weak_students'])} دانش‌آموز در {fa_num(p['schools_count'])} مدرسه ضعیف‌اند؛ "
                    f"خطای غالب: {p['dominant_error_fa'] or '—'}؛ پیش‌نیاز: "
                    f"{'، '.join(p['prerequisites']) or '—'}."
                ),
                "school_id": None,
            }
        )
    for row in school_rows:
        for flag in row["flags"]:
            if flag["severity"] == "positive":
                alerts.append(
                    {
                        "level": "positive",
                        "level_fa": SEVERITY_FA["positive"],
                        "title_fa": f"{row['name']} — {flag['title_fa']}",
                        "message_fa": flag["detail_fa"],
                        "school_id": row["id"],
                    }
                )
    level_order = {"critical": 0, "attention": 1, "forming": 2, "positive": 3}
    alerts.sort(key=lambda a: level_order.get(a["level"], 9))

    severity_counts = {key: 0 for key in SEVERITY_FA}
    for row in school_rows:
        severity_counts[row["severity"]] += 1

    return {
        "district_id": district_id,
        "min_group": s.min_group_size,
        "district_growth": district_growth,
        "schools": school_rows,
        "classes": class_rows,
        "problems": problems,
        "alerts": alerts,
        "severity_counts": severity_counts,
        "thresholds": {
            "stagnation_growth_max": STAGNATION_GROWTH_MAX,
            "divergence_delta": DIVERGENCE_DELTA,
            "prereq_weak_ratio": PREREQ_WEAK_RATIO,
            "common_problem_min_schools": COMMON_PROBLEM_MIN_SCHOOLS,
        },
        "note_fa": (
            "همه موارد «هشدار/پرچم» هستند، نه اتهام یا ارزیابی قطعی درباره معلم؛ اعداد زیر "
            f"حداقل جمعیت {fa_num(s.min_group_size)} نفر سرکوب می‌شوند (district spec §9، §11، §29، §30)."
        ),
    }


# ------------------------- §7/§8/§23 تحلیل خطای ناحیه -------------------------


async def error_analysis(db: AsyncSession, district_id: int) -> dict:
    """طبقه‌بندی خطاها در سطح ناحیه (§23): سهم هر نوع خطا + تفکیک مدرسه +
    مباحث پرتکرار — با قاعده حداقل جمعیت."""
    s = get_settings()
    bundle = await district_bundle(db, district_id)
    errors = bundle["errors"]
    students_with_errors = {e.student_user_id for e in errors}
    suppressed = bool(errors) and len(students_with_errors) < s.min_group_size

    cause_counts: dict[str, int] = {}
    for e in errors:
        cause_counts[e.cause] = cause_counts.get(e.cause, 0) + 1
    total = len(errors)
    causes = [
        {
            "key": key,
            "title_fa": ERROR_CAUSE_FA.get(key, key),
            "count": None if suppressed else count,
            "pct": None if suppressed or not total else round(100.0 * count / total, 1),
        }
        for key, count in sorted(cause_counts.items(), key=lambda kv: -kv[1])
    ]

    schools_rows = []
    for school in bundle["schools"]:
        profiles = [p for p in bundle["profiles"] if p.school_id == school.id]
        ids = {p.user_id for p in profiles}
        school_errors = [e for e in errors if e.student_user_id in ids]
        school_students = {e.student_user_id for e in school_errors}
        school_suppressed = bool(school_errors) and len(school_students) < s.min_group_size
        counts: dict[str, int] = {}
        for e in school_errors:
            counts[e.cause] = counts.get(e.cause, 0) + 1
        schools_rows.append(
            {
                "school_id": school.id,
                "name": school.name,
                "total": None if school_suppressed else len(school_errors),
                "students": None if school_suppressed else len(school_students),
                "causes": None
                if school_suppressed
                else {
                    ERROR_CAUSE_FA.get(k, k): v for k, v in sorted(counts.items(), key=lambda kv: -kv[1])
                },
                "suppressed": school_suppressed,
            }
        )
    schools_rows.sort(key=lambda r: (r["suppressed"], -(r["total"] or 0)))

    by_topic: dict[int, list[ErrorRecord]] = {}
    for e in errors:
        by_topic.setdefault(e.topic_id, []).append(e)
    topic_rows = []
    for topic_id, rows in sorted(by_topic.items(), key=lambda kv: -len(kv[1])):
        counts: dict[str, int] = {}
        for e in rows:
            counts[e.cause] = counts.get(e.cause, 0) + 1
        topic_rows.append(
            {
                "topic_id": topic_id,
                "title": bundle["topics"][topic_id].title_fa if topic_id in bundle["topics"] else f"#{topic_id}",
                "count": len(rows),
                "dominant_error": max(counts, key=counts.get),
                "dominant_error_fa": ERROR_CAUSE_FA.get(max(counts, key=counts.get), "-"),
            }
        )

    return {
        "district_id": district_id,
        "total": None if suppressed else total,
        "students": None if suppressed else len(students_with_errors),
        "suppressed": suppressed,
        "min_group": s.min_group_size,
        "causes": causes,
        "schools": schools_rows,
        "topics": topic_rows[:10],
        "note_fa": (
            "خطاها در سطح ناحیه تجمیع می‌شوند تا معلوم شود مشکل بیشتر «از چه جنسی» است و "
            "مداخله متناسب انتخاب شود (district spec §23)."
            if not suppressed
            else f"خطاهای این ناحیه از کمتر از {fa_num(s.min_group_size)} دانش‌آموز ثبت شده است؛ عدد نمایش داده نمی‌شود."
        ),
    }


# ------------------------- §31 گزارش ناحیه -------------------------


async def district_report_payload(
    db: AsyncSession, district_id: int, period_start: date, period_end: date
) -> dict:
    """محتوای گزارش مدیریتی ناحیه (§31) — مدارس، پایه‌ها، کلاس‌ها، آزمون،
    خطا، مداخله و مرکز توجه؛ همه تجمیعی و با همان قواعد حداقل جمعیت."""
    s = get_settings()
    comparison = await school_comparison(db, district_id)
    growth = await school_growth(db, district_id)
    axes = await health_axes(db, district_id)
    errors = await error_analysis(db, district_id)
    attention = await attention_center(db, district_id)

    bundle = await district_bundle(db, district_id)
    by_grade: dict[str, list] = {}
    for p in bundle["profiles"]:
        by_grade.setdefault(p.grade, []).append(p)
    grades = []
    for grade, profiles in sorted(by_grade.items()):
        ids = {p.user_id for p in profiles}
        with_data = [
            st for st in bundle["states"] if st.student_user_id in ids and st.evidence_count >= s.evidence_min_for_status
        ]
        suppressed = len({st.student_user_id for st in with_data}) < s.min_group_size
        g = _growth_of(with_data)
        weak_topics = sorted(
            {
                (st.topic_id, status_of(st.effective_mastery, st.evidence_count))
                for st in with_data
                if status_of(st.effective_mastery, st.evidence_count) in ("weak", "critical")
            }
        )
        grades.append(
            {
                "grade": grade,
                "students_count": len(profiles),
                "suppressed": suppressed,
                "avg_mastery": None if suppressed else g["current"],
                "growth": None if suppressed else g["growth"],
                "weak_topics": [
                    {
                        "topic_id": topic_id,
                        "title": bundle["topics"][topic_id].title_fa if topic_id in bundle["topics"] else f"#{topic_id}",
                    }
                    for topic_id, _st in weak_topics[:5]
                ],
            }
        )

    # آزمون‌های رسمی ناحیه در بازه
    from app.models.district_exams import DistrictExam

    exams = list(
        (
            await db.execute(select(DistrictExam).where(DistrictExam.district_id == district_id))
        ).scalars()
    )
    exam_by_status: dict[str, int] = {}
    for e in exams:
        exam_by_status[e.status] = exam_by_status.get(e.status, 0) + 1

    interventions = list(
        (
            await db.execute(
                select(DistrictIntervention).where(DistrictIntervention.district_id == district_id)
            )
        ).scalars()
    )
    iv_rows = [
        {
            "id": iv.id,
            "title_fa": iv.title_fa,
            "type": iv.type,
            "status": iv.status,
            "before": iv.before_mastery,
            "after": iv.after_mastery,
            "retention": iv.retention_mastery,
            "effect": (
                None
                if iv.before_mastery is None or iv.after_mastery is None
                else round((iv.after_mastery or 0) - (iv.before_mastery or 0), 1)
            ),
        }
        for iv in interventions
    ]

    percents = [float(a.percent) for a, _ex in bundle["attempts"] if a.percent is not None]
    summary = {
        "schools_count": len(bundle["schools"]),
        "students_count": len(bundle["profiles"]),
        "avg_mastery": axes["axes"][1]["value"],
        "growth": growth["district"]["growth"],
        "exam_avg": round(sum(percents) / len(percents), 1) if percents else None,
        "needs_attention_schools": sum(
            1 for r in attention["schools"] if r["severity"] in ("critical", "attention", "forming")
        ),
        "positive_schools": attention["severity_counts"].get("positive", 0),
        "common_problems": len(attention["problems"]),
    }

    return {
        "period": {"start": period_start.isoformat(), "end": period_end.isoformat()},
        "generated_at": datetime.utcnow().isoformat(),
        "summary": summary,
        "schools": [
            {
                "school_id": row["school_id"],
                "name": row["name"],
                "students_count": row["students_count"],
                "current_mastery": row["current_mastery"],
                "growth": row["growth"],
                "needs_intervention_pct": row["needs_intervention_pct"],
                "suppressed": row["suppressed"],
            }
            for row in comparison["rows"]
        ],
        "grades": grades,
        "classes": [
            {
                "name": row["name"],
                "grade": row["grade"],
                "current_mastery": row["current_mastery"],
                "growth": row["growth"],
                "severity_fa": row["severity_fa"],
                "suppressed": row["suppressed"],
            }
            for row in attention["classes"]
        ],
        "exams": {"total": len(exams), "by_status": exam_by_status, "avg_percent": summary["exam_avg"]},
        "interventions": iv_rows,
        "errors": {
            "total": errors["total"],
            "causes": errors["causes"],
            "suppressed": errors["suppressed"],
        },
        "health_axes": [
            {"title_fa": a["title_fa"], "value": a["value"], "unit": a["unit"], "band": a["band"]}
            for a in axes["axes"]
        ],
        "attention": {
            "severity_counts": attention["severity_counts"],
            "problems": attention["problems"][:5],
        },
        "note_fa": (
            "گزارش فقط از داده‌های تجمیعی همین ناحیه ساخته می‌شود؛ جزئیات خصوصی دانش‌آموزان "
            "بدون مجوز جداگانه وارد گزارش نمی‌شود (district spec §31، §35)."
        ),
    }
