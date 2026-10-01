"""School admin analytics (سند پنل مدیر مدرسه §3 تا §8):
- مقایسه کلاس‌های یک درس (§7)
- سامانه معلم/کلاس «نیازمند بررسی» (§5, §11 ناحیه) — پرچم، نه حکم
- تشخیص چندعاملی ضعف (§6) — شش علت + عوامل زمینه‌ای
- نمایه دوگانه معلم (نسخه سبک §4) — آموزشی + رفتار پلتفرم

اصل سراسری: سیستم هرگز نمی‌گوید «این معلم ضعیف است»؛ می‌گوید
«الگوی غیرعادی دیده می‌شود و نیازمند بررسی مدیریتی است»."""
from __future__ import annotations

from collections import Counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.assessment import AttemptAnswer
from app.models.catalog import Topic
from app.models.org import (
    ClassRoom,
    ClassTeacherAssignment,
    School,
    StudentProfile,
    User,
)
from app.models.slm import ErrorRecord, StudentTopicState
from app.services.slm import status_of
from app.services.teacher import NEED_FA, NEED_ACTION_FA

# آستانه «کلاس دارای افت»: افت ≥ 10 واحد نسبت به میانگین کلاس‌های دیگر همان درس
# (ضمیمه الف سند مدیر مدرسه: ≥۱۰٪ نسبت به دوره قبل — اینجا نسبت به هم‌درس‌ها)
DROP_VS_PEERS_UNITS = 10.0

# آستانه جمعیت برای مقایسه معنادار (ضمیمه الف: حداقل ۱۰ نفر — دموی ۳ نفره با پارامتر)
MIN_GROUP_FOR_COMPARISON = 3


async def _school_classes(db: AsyncSession, school_id: int) -> list[ClassRoom]:
    return list(
        (await db.execute(select(ClassRoom).where(ClassRoom.school_id == school_id))).scalars()
    )


async def _topic_titles(db: AsyncSession) -> dict[int, str]:
    return {t.id: t.title_fa for t in (await db.execute(select(Topic))).scalars()}


async def _states_for_class(db: AsyncSession, class_id: int) -> list[StudentTopicState]:
    ids = [
        p.user_id
        for p in (
            await db.execute(select(StudentProfile).where(StudentProfile.class_id == class_id))
        ).scalars()
    ]
    if not ids:
        return []
    return list(
        (await db.execute(select(StudentTopicState).where(StudentTopicState.student_user_id.in_(ids)))).scalars()
    )


async def _errors_for_class(db: AsyncSession, class_id: int) -> list[ErrorRecord]:
    ids = [
        p.user_id
        for p in (
            await db.execute(select(StudentProfile).where(StudentProfile.class_id == class_id))
        ).scalars()
    ]
    if not ids:
        return []
    return list(
        (await db.execute(select(ErrorRecord).where(ErrorRecord.student_user_id.in_(ids)))).scalars()
    )


async def class_subject_summary(db: AsyncSession, class_id: int, subject: str | None = None) -> dict:
    """خلاصه آموزشی یک کلاس: تسلط/ماندگاری کلاس + توزیع علت خطا (ورودی مقایسه و تشخیص)."""
    states = await _states_for_class(db, class_id)
    errors = await _errors_for_class(db, class_id)

    mastery_vals = [s.effective_mastery for s in states]
    retention_vals = [s.retention for s in states]
    causes = Counter(e.cause for e in errors)
    total_errors = sum(causes.values())

    weak_states = [s for s in states if s.effective_mastery < get_settings().threshold_consolidating]
    top_weak_topics = Counter(s.topic_id for s in weak_states).most_common(3)

    titles = await _topic_titles(db)

    return {
        "class_id": class_id,
        "avg_mastery": round(sum(mastery_vals) / len(mastery_vals), 1) if mastery_vals else None,
        "avg_retention": round(sum(retention_vals) / len(retention_vals), 3) if retention_vals else None,
        "students_with_data": len({s.student_user_id for s in states}),
        "total_errors": total_errors,
        "error_causes": dict(causes),
        "weak_topics": [
            {"topic_id": tid, "title": titles.get(tid, f"#{tid}"), "weak_students": n}
            for tid, n in top_weak_topics
        ],
    }


async def compare_classes(db: AsyncSession, school_id: int, subject: str) -> dict:
    """§7 مقایسه کلاس‌های یک درس: تسلط، ماندگاری، تمرین/خطا، وضعیت.
    با جمعیت کم مقایسه فقط نمایشی است و پرچم نمی‌سازد (MIN_GROUP)."""
    classes = [c for c in await _school_classes(db, school_id)]
    rows = []
    for c in classes:
        # مبحث این مقایسه، کلاس‌هایی است که در همان پایه درس مشترک دارند؛
        # در دیتامدل ما درس از طریق تخصیص معلم → subject مشخص می‌شود.
        links = (
            await db.execute(
                select(ClassTeacherAssignment).where(
                    ClassTeacherAssignment.class_id == c.id,
                    ClassTeacherAssignment.subject == subject,
                    ClassTeacherAssignment.status == "active",
                )
            )
        ).scalars().all()
        if not links:
            continue
        summary = await class_subject_summary(db, c.id)
        summary["class_name"] = c.name
        summary["grade"] = c.grade
        summary["teacher"] = None
        link = links[0]
        teacher = await db.get(User, link.teacher_user_id)
        if teacher:
            summary["teacher"] = {"id": teacher.id, "full_name": teacher.full_name}
        rows.append(summary)

    enough = len(rows) >= 2
    if enough:
        masteries = [r["avg_mastery"] for r in rows if r["avg_mastery"] is not None]
        ref = round(sum(masteries) / len(masteries), 1) if masteries else None
        for r in rows:
            r["gap_vs_school_avg"] = (
                round(r["avg_mastery"] - ref, 1) if r["avg_mastery"] is not None and ref is not None else None
            )
            r["drop_flag"] = (
                r["gap_vs_school_avg"] is not None
                and r["gap_vs_school_avg"] <= -DROP_VS_PEERS_UNITS
                and r["students_with_data"] >= MIN_GROUP_FOR_COMPARISON
            )
    else:
        for r in rows:
            r["gap_vs_school_avg"] = None
            r["drop_flag"] = False

    rows.sort(key=lambda r: (r["avg_mastery"] if r["avg_mastery"] is not None else 999))
    return {
        "school_id": school_id,
        "subject": subject,
        "comparison_valid": enough,
        "min_group_note": f"مقایسه معنادار فقط با حداقل {MIN_GROUP_FOR_COMPARISON} دانش‌آموز دارای داده در هر کلاس",
        "rows": rows,
    }


async def _platform_behavior(db: AsyncSession, class_id: int) -> dict:
    """رفتار پلتفرمی معلم (نسخه سبک §4): آزمون برگزارشده و سرعت ثبت.
    بدون امتیازدهی عددی؛ فقط شاخص‌های عینی برای مدیر."""
    ids = [
        p.user_id
        for p in (
            await db.execute(select(StudentProfile).where(StudentProfile.class_id == class_id))
        ).scalars()
    ]
    answers = (
        await db.execute(select(AttemptAnswer).where(AttemptAnswer.student_user_id.in_(ids)))
    ).scalars().all() if ids else []
    distinct_exams = len({a.attempt_id for a in answers})
    return {
        "exam_sessions_recorded": distinct_exams,
        "answers_recorded": len(answers),
    }


async def attention_flags(db: AsyncSession, school_id: int) -> dict:
    """§5 سامانه «نیازمند بررسی»: پرچم‌های مشخص با شرط قابل توضیح.
    هر پرچم فقط یعنی «بررسی کن» — رتبه‌بندی معلم نیست."""
    settings = get_settings()
    classes = await _school_classes(db, school_id)
    flags: list[dict] = []

    for c in classes:
        links = (
            await db.execute(
                select(ClassTeacherAssignment).where(
                    ClassTeacherAssignment.class_id == c.id,
                    ClassTeacherAssignment.status == "active",
                )
            )
        ).scalars().all()
        if not links:
            continue
        link = links[0]
        teacher = await db.get(User, link.teacher_user_id)

        states = await _states_for_class(db, c.id)
        errors = await _errors_for_class(db, c.id)
        if not states:
            continue

        # --- پرچم ۱: تسلط پایین در ≥ ۸۰٪ کلاس (شرط سند §5 هشدار ۱) ---
        with_data = [s for s in states if s.evidence_count >= settings.evidence_min_for_status]
        if with_data:
            weak_ratio = sum(1 for s in with_data if s.effective_mastery < settings.threshold_consolidating) / len(with_data)
            if weak_ratio >= 0.8:
                flags.append(
                    {
                        "class_id": c.id,
                        "class_name": c.name,
                        "subject": link.subject,
                        "teacher_name": teacher.full_name if teacher else None,
                        "flag_type": "low_mastery_majority",
                        "title_fa": "تسلط پایین اکثریت کلاس",
                        "evidence_fa": f"{round(weak_ratio * 100)}٪ کلاس زیر آستانه تثبیت ({len(with_data)} نفر دارای داده)",
                        "action_fa": "بررسی آموزشی کلاس و ریشه‌یابی مباحث ضعیف",
                    }
                )

        # --- پرچم ۲: خطای تکراری بالا (نسخه مدرسه‌ای سند معلم) ---
        repeats = sum(1 for e in errors if e.status in ("open", "relapsed"))
        if errors and repeats / len(errors) >= 0.5:
            flags.append(
                {
                    "class_id": c.id,
                    "class_name": c.name,
                    "subject": link.subject,
                    "teacher_name": teacher.full_name if teacher else None,
                    "flag_type": "high_repeats",
                    "title_fa": "نرخ بالای خطای تکراری/بازگشته",
                    "evidence_fa": f"{repeats} از {len(errors)} خطا هنوز باز یا بازگشته‌اند",
                    "action_fa": "بررسی چرخه ترمیم–بازآزمون در کلاس",
                }
            )

        # --- پرچم ۳: مداخله بی‌اثر (§11 ناحیه — بازآزمون بدون بهبود) ---
        relapsed = sum(1 for e in errors if e.status == "relapsed")
        resolved = sum(1 for e in errors if e.status == "resolved")
        if resolved >= 2 and relapsed >= resolved:
            flags.append(
                {
                    "class_id": c.id,
                    "class_name": c.name,
                    "subject": link.subject,
                    "teacher_name": teacher.full_name if teacher else None,
                    "flag_type": "ineffective_intervention",
                    "title_fa": "مداخله بی‌اثر",
                    "evidence_fa": f"بازگشت خطا ({relapsed}) به اندازه رفع‌شدگی ({resolved}) است",
                    "action_fa": "بازبینی محتوای ترمیمی و کیفیت بازآزمون",
                }
            )

        behavior = await _platform_behavior(db, c.id)
        # --- پرچم ۴: ثبت اطلاعات ضعیف (دوگانه §4 — مشکل آموزشی نیست، مدیریتی است) ---
        if behavior["answers_recorded"] == 0:
            flags.append(
                {
                    "class_id": c.id,
                    "class_name": c.name,
                    "subject": link.subject,
                    "teacher_name": teacher.full_name if teacher else None,
                    "flag_type": "low_platform_usage",
                    "title_fa": "عدم ثبت فعالیت در پلتفرم",
                    "evidence_fa": "هیچ پاسخ آزمونی برای این کلاس ثبت نشده است",
                    "action_fa": "بررسی مدیریتی: آموزش استفاده یا مشکل دسترسی؟ (رفتار پلتفرمی، نه کیفیت تدریس)",
                }
            )

    return {"school_id": school_id, "flags": flags, "note_fa": "این موارد هشدار هستند، نه ارزیابی قطعی از معلم."}


CAUSE_SEVERITY_FA = {
    "conceptual": "ضعف مفهومی — نیازمند آموزش مجدد",
    "prerequisite": "ضعف پیش‌نیاز — مرور پیش‌نیاز قبل از ادامه",
    "calculation": "خطای محاسباتی — تمرین هدفمند محاسبه",
    "careless": "بی‌دقتی — عادت بازبینی و مدیریت زمان",
    "time_management": "کمبود زمان — تمرین زمان‌دار",
    "guess": "حدس — سنجش مجدد با شواهد معتبرتر",
}


async def multi_factor_diagnosis(db: AsyncSession, class_id: int) -> dict:
    """§6 تشخیص چندعاملی ضعف: از توزیع علت خطا تا عوامل زمینه‌ای.
    خروجی قابل اقدام است، نه قضاوت."""
    summary = await class_subject_summary(db, class_id)
    causes = summary["error_causes"]
    total = summary["total_errors"]

    ranked = sorted(causes.items(), key=lambda kv: kv[1], reverse=True)
    dominant = ranked[0] if ranked else None

    actions: list[str] = []
    if dominant:
        share = round(100.0 * dominant[1] / total) if total else 0
        actions.append(
            f"غالب‌ترین علت خطا «{dominant[0]}» با {share}٪ است — {CAUSE_SEVERITY_FA.get(dominant[0], '')}"
        )
    # عوامل زمینه‌ای §6: مشارکت و تکمیل
    states = await _states_for_class(db, class_id)
    if states:
        s = get_settings()
        no_data = sum(1 for st in states if st.evidence_count < s.evidence_min_for_status)
        if no_data:
            actions.append(f"{no_data} دانش‌آموز شواهد کافی ندارند — مشارکت در تمرین بررسی شود")

    for wt in summary["weak_topics"]:
        actions.append(f"مبحث «{wt['title']}»: {wt['weak_students']} دانش‌آموز نیازمند توجه — ریشه‌یابی پیشنهاد شود")

    return {
        "class_id": class_id,
        "class_mastery": summary["avg_mastery"],
        "error_causes": causes,
        "total_errors": total,
        "weak_topics": summary["weak_topics"],
        "grounded_actions_fa": actions or ["داده کافی برای تشخیص وجود ندارد"],
        "note_fa": "هیچ‌کدام از این نتایج حکم درباره کیفیت تدریس نیست؛ ورودی بررسی مدیریتی است.",
    }


async def teacher_lite_profiles(db: AsyncSession, school_id: int) -> dict:
    """نمایه سبک معلمان (§4): فقط شاخص‌های عینی آموزشی + رفتاری، بدون امتیاز کل.
    هر کلاس یک ردیف؛ مقایسه فقط نمایشی با جمعیت کم."""
    classes = await _school_classes(db, school_id)
    rows = []
    for c in classes:
        links = (
            await db.execute(
                select(ClassTeacherAssignment).where(
                    ClassTeacherAssignment.class_id == c.id,
                    ClassTeacherAssignment.status == "active",
                )
            )
        ).scalars().all()
        for link in links:
            teacher = await db.get(User, link.teacher_user_id)
            summary = await class_subject_summary(db, c.id)
            behavior = await _platform_behavior(db, c.id)
            rows.append(
                {
                    "teacher_id": link.teacher_user_id,
                    "teacher_name": teacher.full_name if teacher else None,
                    "subject": link.subject,
                    "class_id": c.id,
                    "class_name": c.name,
                    "students_count": summary["students_with_data"],
                    "class_mastery": summary["avg_mastery"],
                    "class_retention": summary["avg_retention"],
                    "total_errors": summary["total_errors"],
                    "repeat_open_errors": sum(
                        n for cause, n in summary["error_causes"].items() if cause in ("conceptual", "prerequisite")
                    ),
                    "platform": behavior,
                    "note_fa": "شاخص عینی کلاس این معلم است؛ قضاوت نیاز به بررسی زمینه‌ای دارد.",
                }
            )
    rows.sort(key=lambda r: (r["class_mastery"] if r["class_mastery"] is not None else 999))
    return {"school_id": school_id, "profiles": rows}
