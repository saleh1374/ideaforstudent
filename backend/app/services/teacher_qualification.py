"""سرویس صلاحیت معلم (سند صلاحیت — خواسته صریح کارفرما): تخصیص سالانه
دو آزمون (سنجش دانش درس + سنجش مهارت مدیریت کلاس)، برگزاری تلاش و
تصحیح، ارزیابی وضعیت صلاحیت وقتی هر دو آزمون تصحیح شد، و اقدام
اصلاحی ناحیه برای وضعیت‌های بحرانی/آزمایشی.

همه عددسازی‌ها از Settings است («مقدارهای عددی فقط فرض هستند») و هر رویداد
با log_action در لاگ ممیزی ثبت می‌شود."""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.org import Employee, School, SchoolAssignment, User
from app.models.teacher_assessment import (
    TeacherAttemptAnswer,
    TeacherExam,
    TeacherExamAttempt,
    TeacherExamItem,
    TeacherExamQuestion,
    TeacherIntervention,
    TeacherQualification,
)
from app.services import district as district_svc
from app.services.rbac_service import log_action

KIND_SUBJECT = "subject"
KIND_MANAGEMENT = "classroom_management"
KINDS = (KIND_SUBJECT, KIND_MANAGEMENT)

KIND_FA = {
    KIND_SUBJECT: "سنجش دانش درس",
    KIND_MANAGEMENT: "سنجش مهارت مدیریت کلاس",
}

QUALIFICATION_STATUS_FA = {
    "pending": "در انتظار ارزیابی",
    "qualified": "تأیید صلاحیت",
    "probation": "دوره الزامی (آزمایشی)",
    "critical": "بحرانی",
}

INTERVENTION_TYPES = ("training", "mentoring", "replacement")
INTERVENTION_TYPE_FA = {
    "training": "دوره ضمن خدمت",
    "mentoring": "سرپرستی و راهنمایی",
    "replacement": "جایگزینی",
}
INTERVENTION_STATUSES = ("proposed", "scheduled", "done", "cancelled")

SUBJECT_FA = {
    "math": "ریاضی",
    "physics": "فیزیک",
    "chemistry": "شیمی",
    "biology": "زیست‌شناسی",
    "literature": "ادبیات فارسی",
    "arabic": "عربی",
    "english": "زبان انگلیسی",
    "history": "تاریخ",
    "geography": "جغرافیا",
    "religion": "قرآن و تربیت",
}


def subject_fa(subject: str | None) -> str:
    """نام فارسی درس برای روایت‌ها (کد ناشناخته همان کد برمی‌گردد)."""
    if not subject:
        return "—"
    return SUBJECT_FA.get(subject, subject)


def utcnow() -> datetime:
    """زمان حال به وقت UTC بدون tz (ستون‌های DateTime در کد ناهمگام)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def current_school_year(today: datetime | None = None) -> str:
    """سال تحصیلی جاری از تقویم هجری شمسی — قطعی و بدون وابستگی به محیط.
    سال تحصیلی از ۱ مهر شروع می‌شود: از مهر تا پایان اسفند سال جاری
    «jy-jy+1» و در فروردین تا شهریور «jy-1-jy» (مثلاً ۱۴۰۵/۰۷/۰۹ → 1405-1406)."""
    g = (today or utcnow()).date()
    jy, jm = _to_jalali(g.year, g.month, g.day)[:2]
    return f"{jy}-{jy + 1}" if jm >= 7 else f"{jy - 1}-{jy}"


def _to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    """تبدیل میلادی به هجری شمسی (الگوریتم استاندارد بازه‌های جلالی)."""
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if gy > 1600:
        jy, gy = 979, gy - 1600
    else:
        jy, gy = 0, gy - 621
    gy2 = gy + 1 if gm > 2 else gy
    days = (
        365 * gy
        + (gy2 + 3) // 4
        - (gy2 + 99) // 100
        + (gy2 + 399) // 400
        - 80
        + gd
        + g_d_m[gm - 1]
    )
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm, jd = 1 + days // 31, 1 + days % 31
    else:
        jm, jd = 7 + (days - 186) // 30, 1 + (days - 186) % 30
    return jy, jm, jd


# ------------------------- تخصیص سالانه آزمون‌ها -------------------------


async def _active_teaching_assignments(
    db: AsyncSession, teacher_user_id: int, subject: str
) -> list[SchoolAssignment]:
    """تخصیص‌های فعالِ تدریِ همین درس (معلم واقعاً این درس را ارائه می‌دهد)."""
    rows = (
        await db.execute(
            select(SchoolAssignment)
            .join(Employee, Employee.id == SchoolAssignment.employee_id)
            .where(
                Employee.user_id == teacher_user_id,
                SchoolAssignment.role == "teacher",
                SchoolAssignment.status == "active",
                SchoolAssignment.subject == subject,
            )
            .order_by(SchoolAssignment.id)
        )
    ).scalars().all()
    return list(rows)


async def _sampled_bank(
    db: AsyncSession, kind: str, subject: str
) -> list[TeacherExamQuestion]:
    """نمونه‌برداری از بانک سؤالِ هر نوع: subject ← فیلتر درس؛
    classroom_management ← کل بانک. اگر بانک خالی بود 409 (بدون ایجاد
    آزمون ناقص)."""
    s = get_settings()
    q = select(TeacherExamQuestion).where(
        TeacherExamQuestion.kind == kind,
        TeacherExamQuestion.is_active == 1,
    )
    if kind == KIND_SUBJECT:
        q = q.where(TeacherExamQuestion.subject == subject)
    questions = list((await db.execute(q.order_by(TeacherExamQuestion.id))).scalars())
    if not questions:
        label = subject_fa(subject) if kind == KIND_SUBJECT else "مدیریت کلاس"
        raise HTTPException(
            409,
            f"بانک سؤال «{KIND_FA[kind]}» برای {label} کافی نیست؛ ابتدا سؤال ثبت کنید",
        )
    take = min(s.teacher_exam_items, len(questions))
    return random.sample(questions, take)


def exam_row(exam: TeacherExam) -> dict:
    """ردیف خلاصه آزمون برای پاسخ API."""
    return {
        "id": exam.id,
        "kind": exam.kind,
        "kind_fa": KIND_FA.get(exam.kind, exam.kind),
        "title_fa": exam.title_fa,
        "subject": exam.subject,
        "school_year": exam.school_year,
        "status": exam.status,
        "due_at": exam.due_at,
    }


async def exam_percent(db: AsyncSession, exam_id: int | None) -> float | None:
    """درصد آخرین تلاش تصحیح‌شده آزمون (None اگر هنوز ارسال/تصحیح نشده)."""
    if exam_id is None:
        return None
    attempt = (
        await db.execute(
            select(TeacherExamAttempt)
            .where(TeacherExamAttempt.exam_id == exam_id)
            .order_by(TeacherExamAttempt.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if attempt is None or attempt.status != "graded":
        return None
    return attempt.percent


async def assign_year_exams(
    db: AsyncSession,
    teacher_user_id: int,
    subject: str,
    school_year: str,
    assigned_by: int,
    school_id: int | None = None,
    district_id: int | None = None,
) -> dict:
    """تخصیص هر دو آزمون صلاحیت برای (معلم، درس، سال) — idempotent:
    اگر آزمونی از قبل وجود داشته باشد ساخته نمی‌شود و همان بازگردانده
    می‌شود. پیش‌نیاز: تخصیص فعالِ تدریِ همین درس در مدرسه‌ای از ناحیه
    تماس‌گیرنده (حوزه ناحیه — district spec §33)."""
    s = get_settings()
    subject = (subject or "").strip()
    if not subject:
        raise HTTPException(400, "درس الزامی است")
    await db.flush()  # autoflush خاموش است — ردیف‌های تازه (مثلاً بانک سؤال) دیده شوند
    teacher = await db.get(User, teacher_user_id)
    if teacher is None or not teacher.is_active:
        raise HTTPException(404, "معلم یافت نشد")

    # معلم باید واقعاً این درس را در مدرسه‌ای از ناحیه تماس‌گیرنده ارائه دهد
    allowed_school_ids: set[int] | None = None
    if district_id is not None:
        allowed_school_ids = {sc.id for sc in await district_svc.district_schools(db, district_id)}
    assignments = await _active_teaching_assignments(db, teacher_user_id, subject)
    if allowed_school_ids is not None:
        assignments = [a for a in assignments if a.school_id in allowed_school_ids]
    if school_id is not None:
        assignments = [a for a in assignments if a.school_id == school_id]
    if not assignments:
        raise HTTPException(403, "این معلم تخصیص فعالِ تدریِ این درس در ناحیه شما ندارد")

    resolved_school_id = assignments[0].school_id
    school = await db.get(School, resolved_school_id)
    if district_id is None:
        district_id = school.district_id if school is not None else None
    if district_id is None:
        raise HTTPException(400, "مدرسه مربوط به ناحیه‌ای مشخص نیست")

    # آزمون‌های موجودِ همین (معلم، سال): درس با subject_key=درس؛ مدیریت
    # کلاس subject_key="" دارد (یکی در هر سال)
    rows = list(
        (
            await db.execute(
                select(TeacherExam).where(
                    TeacherExam.teacher_user_id == teacher_user_id,
                    TeacherExam.school_year == school_year,
                )
            )
        ).scalars()
    )
    existing: dict[str, TeacherExam] = {}
    for exam_row_ in rows:
        if exam_row_.kind == KIND_SUBJECT and exam_row_.subject_key == subject:
            existing[KIND_SUBJECT] = exam_row_
        elif exam_row_.kind == KIND_MANAGEMENT:
            existing.setdefault(KIND_MANAGEMENT, exam_row_)

    # نمونه‌برداری برای هر نوعی که هنوز ساخته نشده (پیش از هر ایجادی)
    banks: dict[str, list[TeacherExamQuestion]] = {}
    for kind in KINDS:
        if kind not in existing:
            banks[kind] = await _sampled_bank(db, kind, subject)

    created: list[TeacherExam] = []
    for kind in KINDS:
        if kind in existing:
            continue
        title = (
            f"آزمون {KIND_FA[kind]} {subject_fa(subject)} — سال تحصیلی {school_year}"
        )
        exam = TeacherExam(
            kind=kind,
            title_fa=title,
            subject=subject if kind == KIND_SUBJECT else None,
            subject_key=subject if kind == KIND_SUBJECT else "",
            school_year=school_year,
            school_id=resolved_school_id,
            district_id=district_id,
            teacher_user_id=teacher_user_id,
            assigned_by=assigned_by,
            status="assigned",
            due_at=utcnow() + timedelta(days=s.teacher_exam_window_days),
        )
        db.add(exam)
        await db.flush()
        for order, question in enumerate(banks[kind], start=1):
            db.add(
                TeacherExamItem(
                    exam_id=exam.id, question_id=question.id, order=order, points=1.0
                )
            )
        await log_action(
            db,
            actor_user_id=assigned_by,
            action="teacher_exam_assigned",
            entity_type="teacher_exam",
            entity_id=exam.id,
            detail=(
                f"teacher={teacher_user_id} kind={kind} subject={subject} "
                f"year={school_year} school={resolved_school_id}"
            ),
        )
        existing[kind] = exam
        created.append(exam)
    await db.flush()

    # رکورد صلاحیت (idempotent) + پیوند به هر دو آزمون
    qual = (
        await db.execute(
            select(TeacherQualification).where(
                TeacherQualification.teacher_user_id == teacher_user_id,
                TeacherQualification.subject == subject,
                TeacherQualification.school_year == school_year,
            )
        )
    ).scalar_one_or_none()
    if qual is None:
        qual = TeacherQualification(
            teacher_user_id=teacher_user_id,
            subject=subject,
            school_year=school_year,
            school_id=resolved_school_id,
            district_id=district_id,
            status="pending",
        )
        db.add(qual)
        await db.flush()
    qual.school_id = resolved_school_id
    qual.subject_exam_id = existing[KIND_SUBJECT].id
    qual.management_exam_id = existing[KIND_MANAGEMENT].id

    return {
        "ok": True,
        "created": bool(created),
        "qualification_id": qual.id,
        "qualification_status": qual.status,
        "school_year": school_year,
        "exams": [
            exam_row(existing[kind]) for kind in KINDS if kind in existing
        ],
    }


# ------------------------- برگزاری و تصحیح -------------------------


async def start_attempt(
    db: AsyncSession, exam: TeacherExam, teacher_user_id: int
) -> TeacherExamAttempt:
    """شروع (یا ادامه) تلاش معلم — فقط معلمِ خودِ آزمون، فقط در مهلت و
    فقط وقتی آزمون هنوز ارسال نشده است."""
    if exam.teacher_user_id != teacher_user_id:
        raise HTTPException(403, "این آزمون به شما تخصیص نیافته است")
    now = utcnow()
    if exam.status == "completed":
        raise HTTPException(409, "این آزمون قبلاً تکمیل شده است")
    if exam.status == "expired":
        raise HTTPException(409, "مهلت این آزمون به پایان رسیده است")
    if exam.due_at is not None and exam.due_at < now:
        exam.status = "expired"
        await db.flush()
        raise HTTPException(409, "مهلت پاسخ‌گویی به این آزمون گذشته است")

    attempt = (
        await db.execute(
            select(TeacherExamAttempt).where(
                TeacherExamAttempt.exam_id == exam.id,
                TeacherExamAttempt.teacher_user_id == teacher_user_id,
            )
        )
    ).scalar_one_or_none()
    if attempt is not None:
        if attempt.status == "in_progress":
            return attempt
        raise HTTPException(409, "پاسخ این آزمون قبلاً ارسال شده است")

    attempt = TeacherExamAttempt(
        exam_id=exam.id, teacher_user_id=teacher_user_id, status="in_progress"
    )
    db.add(attempt)
    if exam.status == "assigned":
        exam.status = "in_progress"
    await db.flush()
    return attempt


async def attempt_questions(db: AsyncSession, exam: TeacherExam) -> list[dict]:
    """سؤال‌های آزمون برای نمایش به معلم — بدون پاسخ درست (هرگز)."""
    items = (
        await db.execute(
            select(TeacherExamItem)
            .where(TeacherExamItem.exam_id == exam.id)
            .order_by(TeacherExamItem.order)
        )
    ).scalars().all()
    out: list[dict] = []
    for item in items:
        question = await db.get(TeacherExamQuestion, item.question_id)
        if question is None:
            continue
        out.append(
            {
                "id": item.id,
                "order": item.order,
                "body": question.body,
                "options": question.options,
                "points": item.points,
            }
        )
    return out


async def submit_attempt(
    db: AsyncSession, attempt: TeacherExamAttempt, answers: list[dict]
) -> dict:
    """تصحیح: مقایسه با correct_option، درصد = درست/کل×۱۰۰، آزمون completed و
    سپس ارزیابی صلاحیت (فقط وقتی هر دو آزمون تصحیح شده باشند)."""
    if attempt.status != "in_progress":
        raise HTTPException(409, "پاسخ این آزمون قبلاً ارسال شده است")
    exam = await db.get(TeacherExam, attempt.exam_id)
    if exam is None:
        raise HTTPException(404, "آزمون یافت نشد")

    items = list(
        (
            await db.execute(
                select(TeacherExamItem)
                .where(TeacherExamItem.exam_id == exam.id)
                .order_by(TeacherExamItem.order)
            )
        ).scalars()
    )
    if not items:
        raise HTTPException(409, "این آزمون سؤالی ندارد")

    selected: dict[int, str | None] = {}
    for entry in answers:
        item_id = entry.get("item_id")
        option = entry.get("option")
        if item_id in selected:
            raise HTTPException(400, "پاسخ تکراری برای یک سؤال پذیرفته نمی‌شود")
        selected[item_id] = option.strip().upper() if isinstance(option, str) else None
    unknown = {i for i in selected if i not in {it.id for it in items}}
    if unknown:
        raise HTTPException(400, "یک یا چند شناسه سؤال متعلق به این آزمون نیست")

    correct = 0
    for item in items:
        question = await db.get(TeacherExamQuestion, item.question_id)
        chosen = selected.get(item.id)
        is_correct = (
            1 if question is not None and chosen is not None and chosen == question.correct_option else 0
        )
        correct += is_correct
        db.add(
            TeacherAttemptAnswer(
                attempt_id=attempt.id,
                exam_item_id=item.id,
                selected_option=chosen,
                is_correct=is_correct,
            )
        )

    percent = round(correct * 100.0 / len(items), 1)
    attempt.status = "graded"
    attempt.percent = percent
    attempt.submitted_at = utcnow()
    exam.status = "completed"
    await db.flush()

    await log_action(
        db,
        actor_user_id=attempt.teacher_user_id,
        action="teacher_exam_submitted",
        entity_type="teacher_exam",
        entity_id=exam.id,
        detail=f"attempt={attempt.id} correct={correct} total={len(items)} percent={percent}",
    )

    # آزمون مدیریت کلاس ممکن است بین چند درسِ یک معلم مشترک باشد → همه
    # رکوردهای صلاحیتِ متصل به این آزمون ارزیابی می‌شوند
    quals = list(
        (
            await db.execute(
                select(TeacherQualification).where(
                    or_(
                        TeacherQualification.subject_exam_id == exam.id,
                        TeacherQualification.management_exam_id == exam.id,
                    )
                )
            )
        ).scalars()
    )
    qualification_status = None
    if quals:
        primary = next((q for q in quals if q.subject_exam_id == exam.id), quals[0])
        for qual in quals:
            status = await evaluate_qualification(
                db, qual, actor_user_id=attempt.teacher_user_id
            )
            if qual is primary:
                qualification_status = status
    return {
        "percent": percent,
        "status": attempt.status,
        "qualification_status": qualification_status,
    }


async def evaluate_qualification(
    db: AsyncSession, qual: TeacherQualification, actor_user_id: int | None = None
) -> str:
    """ارزیابی صلاحیت وقتی هر دو آزمون تصحیح شده باشند: کمترین درصد دو
    آزمون → ≥ pass: qualified؛ ≥ critical: probation؛ زیر آن: critical."""
    s = get_settings()
    if qual.subject_exam_id is None or qual.management_exam_id is None:
        return qual.status
    sub_percent = await exam_percent(db, qual.subject_exam_id)
    mgmt_percent = await exam_percent(db, qual.management_exam_id)
    if sub_percent is None or mgmt_percent is None:
        return qual.status  # هنوز هر دو تصحیح نشده‌اند → pending می‌ماند

    lowest = min(sub_percent, mgmt_percent)
    if lowest >= s.teacher_pass_score:
        new_status = "qualified"
        note = (
            f"درصد درس {sub_percent} و مدیریت کلاس {mgmt_percent} — بالای حد قبول "
            f"{s.teacher_pass_score}؛ صلاحیت تدریس تأیید شد."
        )
    elif lowest >= s.teacher_critical_score:
        new_status = "probation"
        note = (
            f"کمترین درصد دو آزمون {lowest} (درس {sub_percent}، مدیریت کلاس "
            f"{mgmt_percent}) — بالای حد بحران {s.teacher_critical_score} اما زیر حد "
            f"قبول {s.teacher_pass_score}؛ دوره ضمن خدمت الزامی است."
        )
    else:
        new_status = "critical"
        note = (
            f"کمترین درصد دو آزمون {lowest} (درس {sub_percent}، مدیریت کلاس "
            f"{mgmt_percent}) — زیر حد بحران {s.teacher_critical_score}؛ ناحیه باید "
            "اقدام اصلاحی (دوره، سرپرستی یا جایگزینی) ثبت کند."
        )

    old_status = qual.status
    qual.subject_percent = sub_percent
    qual.management_percent = mgmt_percent
    qual.status = new_status
    qual.status_note = note
    qual.evaluated_at = utcnow()
    await db.flush()
    await log_action(
        db,
        actor_user_id=actor_user_id,
        action="qualification_status_changed",
        entity_type="teacher_qualification",
        entity_id=qual.id,
        detail=(
            f"old={old_status} new={new_status} subject_percent={sub_percent} "
            f"management_percent={mgmt_percent} teacher={qual.teacher_user_id}"
        ),
    )
    return new_status


# ------------------------- اقدام اصلاحی ناحیه -------------------------


def intervention_row(row: TeacherIntervention) -> dict:
    return {
        "id": row.id,
        "qualification_id": row.qualification_id,
        "type": row.type,
        "type_fa": INTERVENTION_TYPE_FA.get(row.type, row.type),
        "status": row.status,
        "notes": row.notes,
        "created_by": row.created_by,
        "created_at": row.created_at,
        "closed_at": row.closed_at,
    }


async def record_intervention(
    db: AsyncSession,
    qualification: TeacherQualification,
    type: str,
    notes: str | None,
    created_by: int,
) -> TeacherIntervention:
    """ثبت اقدام اصلاحی — فقط برای وضعیت probation/critical (وگرنه 409)."""
    if type not in INTERVENTION_TYPES:
        raise HTTPException(
            400, "نوع اقدام نامعتبر است (training | mentoring | replacement)"
        )
    if qualification.status not in ("probation", "critical"):
        raise HTTPException(
            409,
            "اقدام اصلاحی فقط برای صلاحیت در وضعیت آزمایشی یا بحرانی مجاز است",
        )
    row = TeacherIntervention(
        qualification_id=qualification.id,
        type=type,
        status="proposed",
        notes=notes,
        created_by=created_by,
    )
    db.add(row)
    await db.flush()
    await log_action(
        db,
        actor_user_id=created_by,
        action="teacher_intervention_created",
        entity_type="teacher_qualification",
        entity_id=qualification.id,
        detail=(
            f"intervention={row.id} type={type} teacher={qualification.teacher_user_id} "
            f"status={qualification.status}"
        ),
    )
    return row


async def update_intervention_status(
    db: AsyncSession, row: TeacherIntervention, status: str
) -> TeacherIntervention:
    """به‌روزرسانی وضعیت اقدام؛ بسته‌شدن نرم (done/cancelled) با closed_at."""
    if status not in INTERVENTION_STATUSES:
        raise HTTPException(
            400, "وضعیت نامعتبر است (proposed | scheduled | done | cancelled)"
        )
    row.status = status
    if status in ("done", "cancelled") and row.closed_at is None:
        row.closed_at = utcnow()
    await db.flush()
    return row


# ------------------------- فهرست‌های ناحیه‌ای و نمای معلم -------------------------


async def _qual_row(db: AsyncSession, qual: TeacherQualification) -> dict:
    """ردیف رکورد صلاحیت با درصد زنده هر آزمون + شمار اقدام‌ها."""
    teacher = await db.get(User, qual.teacher_user_id)
    school = await db.get(School, qual.school_id) if qual.school_id else None
    interventions = list(
        (
            await db.execute(
                select(TeacherIntervention).where(
                    TeacherIntervention.qualification_id == qual.id
                )
            )
        ).scalars()
    )
    return {
        "id": qual.id,
        "teacher_user_id": qual.teacher_user_id,
        "teacher_name": teacher.full_name if teacher else None,
        "subject": qual.subject,
        "subject_fa": subject_fa(qual.subject),
        "school_year": qual.school_year,
        "school_id": qual.school_id,
        "school_name": school.name if school else None,
        "district_id": qual.district_id,
        "status": qual.status,
        "status_fa": QUALIFICATION_STATUS_FA.get(qual.status, qual.status),
        "subject_percent": await exam_percent(db, qual.subject_exam_id)
        if qual.subject_percent is None
        else qual.subject_percent,
        "management_percent": await exam_percent(db, qual.management_exam_id)
        if qual.management_percent is None
        else qual.management_percent,
        "subject_exam_id": qual.subject_exam_id,
        "management_exam_id": qual.management_exam_id,
        "status_note": qual.status_note,
        "evaluated_at": qual.evaluated_at,
        "interventions_count": len(interventions),
        "created_at": qual.created_at,
        "updated_at": qual.updated_at,
    }


async def district_teachers(db: AsyncSession, district_id: int) -> list[dict]:
    """معلمان دارای تخصیص فعال در مدرسه‌های ناحیه + وضعیت صلاحیت سال جاری
    (برای dropdown پنل ناحیه و خلاصه وضعیت)."""
    schools = await district_svc.district_schools(db, district_id)
    school_ids = [sc.id for sc in schools]
    school_names = {sc.id: sc.name for sc in schools}
    if not school_ids:
        return []
    assignments = list(
        (
            await db.execute(
                select(SchoolAssignment)
                .join(Employee, Employee.id == SchoolAssignment.employee_id)
                .where(
                    SchoolAssignment.school_id.in_(school_ids),
                    SchoolAssignment.role == "teacher",
                    SchoolAssignment.status == "active",
                )
                .order_by(SchoolAssignment.id)
            )
        ).scalars()
    )
    employee_ids = [a.employee_id for a in assignments]
    employees = {
        e.id: e
        for e in (
            await db.execute(select(Employee).where(Employee.id.in_(employee_ids)))
        ).scalars()
    } if employee_ids else {}
    user_ids = [e.user_id for e in employees.values()]
    users = {
        u.id: u
        for u in (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars()
    } if user_ids else {}

    year = current_school_year()
    quals = list(
        (
            await db.execute(
                select(TeacherQualification).where(
                    TeacherQualification.district_id == district_id,
                    TeacherQualification.school_year == year,
                )
            )
        ).scalars()
    )
    status_by = {(q.teacher_user_id, q.subject): q.status for q in quals}

    rows: list[dict] = []
    for assignment in assignments:
        employee = employees.get(assignment.employee_id)
        user = users.get(employee.user_id) if employee else None
        if user is None or not user.is_active:
            continue
        rows.append(
            {
                "user_id": user.id,
                "full_name": user.full_name,
                "school_id": assignment.school_id,
                "school_name": school_names.get(assignment.school_id),
                "subject": assignment.subject,
                "qualification_status_current_year": status_by.get(
                    (user.id, assignment.subject)
                ),
            }
        )
    rows.sort(key=lambda r: (r["full_name"], r["subject"] or ""))
    return rows


async def district_qualifications(
    db: AsyncSession,
    district_id: int,
    status: str | None = None,
    school_id: int | None = None,
    subject: str | None = None,
    school_year: str | None = None,
) -> list[dict]:
    """رکوردهای صلاحیت ناحیه با فیلترهای (وضعیت، مدرسه، درس، سال)."""
    q = (
        select(TeacherQualification)
        .where(TeacherQualification.district_id == district_id)
        .order_by(TeacherQualification.id)
    )
    if status is not None:
        q = q.where(TeacherQualification.status == status)
    if school_id is not None:
        q = q.where(TeacherQualification.school_id == school_id)
    if subject is not None:
        q = q.where(TeacherQualification.subject == subject)
    if school_year is not None:
        q = q.where(TeacherQualification.school_year == school_year)
    rows = list((await db.execute(q)).scalars())
    return [await _qual_row(db, row) for row in rows]


async def district_qualification_or_404(
    db: AsyncSession, qualification_id: int, district_id: int
) -> TeacherQualification:
    """رکورد صلاحیت فقط از همین ناحیه (وگرنه 404 — ایزوله‌بودن حوزه)."""
    qual = await db.get(TeacherQualification, qualification_id)
    if qual is None or qual.district_id != district_id:
        raise HTTPException(404, "رکورد صلاحیت در ناحیه شما یافت نشد")
    return qual


async def qualification_detail(
    db: AsyncSession, qual: TeacherQualification
) -> dict:
    """جزئیات رکورد: خودِ رکورد + آزمون‌ها + تلاش‌ها + تاریخچه اقدام‌ها."""
    row = await _qual_row(db, qual)
    exam_ids = [e for e in (qual.subject_exam_id, qual.management_exam_id) if e]
    exam_by_id: dict[int, TeacherExam] = {}
    exams: list[dict] = []
    for exam_id in exam_ids:
        exam_obj = await db.get(TeacherExam, exam_id)
        if exam_obj is None:
            continue
        exam_by_id[exam_id] = exam_obj
        exams.append({**exam_row(exam_obj), "percent": await exam_percent(db, exam_id)})

    attempts = list(
        (
            await db.execute(
                select(TeacherExamAttempt)
                .where(TeacherExamAttempt.exam_id.in_(exam_ids))
                .order_by(TeacherExamAttempt.id)
            )
        ).scalars()
    ) if exam_ids else []
    attempt_rows = []
    for attempt in attempts:
        exam = exam_by_id.get(attempt.exam_id)
        attempt_rows.append(
            {
                "id": attempt.id,
                "exam_id": attempt.exam_id,
                "kind": exam.kind if exam else None,
                "kind_fa": KIND_FA.get(exam.kind, exam.kind) if exam else None,
                "status": attempt.status,
                "percent": attempt.percent,
                "started_at": attempt.started_at,
                "submitted_at": attempt.submitted_at,
            }
        )

    interventions = list(
        (
            await db.execute(
                select(TeacherIntervention)
                .where(TeacherIntervention.qualification_id == qual.id)
                .order_by(TeacherIntervention.id)
            )
        ).scalars()
    )
    return {
        "qualification": row,
        "exams": exams,
        "attempts": attempt_rows,
        "interventions": [intervention_row(r) for r in interventions],
    }


async def teacher_assessments(
    db: AsyncSession, teacher_user_id: int, school_year: str
) -> dict:
    """نمای خودِ معلم: آزمون‌های سال جاری + رکوردهای صلاحیت او."""
    exams = list(
        (
            await db.execute(
                select(TeacherExam)
                .where(
                    TeacherExam.teacher_user_id == teacher_user_id,
                    TeacherExam.school_year == school_year,
                )
                .order_by(TeacherExam.id)
            )
        ).scalars()
    )
    quals = list(
        (
            await db.execute(
                select(TeacherQualification)
                .where(TeacherQualification.teacher_user_id == teacher_user_id)
                .order_by(TeacherQualification.id)
            )
        ).scalars()
    )
    qual_by_id = {q.id: q for q in quals}
    qual_by_exam: dict[int, TeacherQualification] = {}
    for qual in quals:
        if qual.subject_exam_id:
            qual_by_exam[qual.subject_exam_id] = qual
        if qual.management_exam_id:
            qual_by_exam[qual.management_exam_id] = qual

    def _qual_brief(qual: TeacherQualification | None) -> dict | None:
        if qual is None:
            return None
        return {
            "id": qual.id,
            "subject": qual.subject,
            "subject_fa": subject_fa(qual.subject),
            "school_year": qual.school_year,
            "status": qual.status,
            "status_fa": QUALIFICATION_STATUS_FA.get(qual.status, qual.status),
            "status_note": qual.status_note,
            "evaluated_at": qual.evaluated_at,
        }

    exam_rows = []
    for exam in exams:
        exam_rows.append(
            {
                **exam_row(exam),
                "percent": await exam_percent(db, exam.id),
                "qualification": _qual_brief(qual_by_exam.get(exam.id)),
            }
        )
    return {
        "school_year": school_year,
        "exams": exam_rows,
        "qualifications": [
            {
                **await _qual_row(db, qual),
                "status_fa": QUALIFICATION_STATUS_FA.get(qual.status, qual.status),
            }
            for qual in quals
            if qual.school_year == school_year
        ],
    }
