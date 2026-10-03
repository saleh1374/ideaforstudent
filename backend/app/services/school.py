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
from app.models.catalog import Book, Chapter, Topic
from app.models.org import (
    ClassRoom,
    ClassTeacherAssignment,
    School,
    StudentProfile,
    User,
)
from app.models.slm import ErrorRecord, PlanTask, StudentTopicState
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

# شش علت خطای سند دانش‌آموز + دو عامل رفتاری/سازمانیِ تازه در این سطح (§6.1)
DIAGNOSIS_CAUSES = tuple(CAUSE_SEVERITY_FA)


async def _class_student_ids(db: AsyncSession, class_id: int) -> list[int]:
    return [
        p.user_id
        for p in (
            await db.execute(select(StudentProfile).where(StudentProfile.class_id == class_id))
        ).scalars()
    ]


async def diagnosis_factors(db: AsyncSession, class_id: int) -> dict:
    """§6.1 عوامل تشخیص چندعاملی: شش علت خطا + «عدم انجام تمرین» و «غیبت»
    (رفتاری) + «مشکلات آموزشی کلاس» (سازمانی) — هر عامل با شاخص عددی یا
    نبودِ دادهٔ صریح (هرگز صفر ساختگی). سه حالت الف/ب/ج هم از همین شواهد
    ساخته می‌شود تا نتیجه‌گیری شتاب‌زده نشود."""
    settings = get_settings()
    summary = await class_subject_summary(db, class_id)
    causes: dict = summary["error_causes"]
    total = summary["total_errors"]
    student_ids = await _class_student_ids(db, class_id)

    factors: list[dict] = []
    for cause in DIAGNOSIS_CAUSES:
        n = causes.get(cause, 0)
        factors.append(
            {
                "key": cause,
                "group": "cause",
                "label_fa": cause,
                "label_full_fa": CAUSE_SEVERITY_FA[cause],
                "source_fa": "از سند دانش‌آموز",
                "count": n,
                "share_pct": round(100.0 * n / total, 1) if total else 0.0,
                "has_data": total > 0,
            }
        )

    # ---- عامل رفتاری ۱: عدم انجام تمرین (نرخ تکمیل کارهای برنامه) ----
    tasks = (
        (await db.execute(select(PlanTask).where(PlanTask.student_user_id.in_(student_ids)))).scalars().all()
        if student_ids
        else []
    )
    done = sum(1 for t in tasks if t.status == "done")
    completion_pct = round(100.0 * done / len(tasks), 1) if tasks else None
    factors.append(
        {
            "key": "no_practice",
            "group": "behavioral",
            "label_fa": "عدم انجام تمرین",
            "source_fa": "رفتاری — جدید در این سطح",
            "value_pct": completion_pct,
            "count": len(tasks) - done,
            "has_data": bool(tasks),
            "note_fa": "نرخ تکمیل کارهای برنامهٔ یادگیری هر دانش‌آموز" if tasks else "هنوز کار برنامه‌ای برای این کلاس ثبت نشده است",
        }
    )

    # ---- عامل رفتاری ۲: غیبت (دادهٔ حضور هنوز در سامانه نیست — صریح و بدون حدس) ----
    factors.append(
        {
            "key": "absence",
            "group": "behavioral",
            "label_fa": "غیبت",
            "source_fa": "رفتاری — جدید در این سطح",
            "value_pct": None,
            "count": None,
            "has_data": False,
            "note_fa": "حضور و غیاب هنوز در سامانه ثبت نمی‌شود؛ در صورت اتصال، همین عامل عددی می‌شود.",
        }
    )

    # ---- عامل سازمانی: مشکلات آموزشی کلاس (از مباحث ضعیفِ شناسایی‌شده) ----
    weak_topics = summary["weak_topics"]
    factors.append(
        {
            "key": "class_issues",
            "group": "organizational",
            "label_fa": "مشکلات آموزشی کلاس",
            "source_fa": "سازمانی — بخش مشترک کلاس",
            "count": len(weak_topics),
            "value_pct": None,
            "has_data": bool(weak_topics),
            "note_fa": "مباحثی که بخش بزرگی از کلاس همزمان در آن زیر آستانه‌اند",
        }
    )

    # ---- سه حالت نمونهٔ §6.1 (الف/ب/ج) ----
    states = await _states_for_class(db, class_id)
    with_data = [s for s in states if s.evidence_count >= settings.evidence_min_for_status]
    relapsed = sum(1 for e in await _errors_for_class(db, class_id) if e.status == "relapsed")
    dominant = max(causes.items(), key=lambda kv: kv[1]) if causes else None
    dominant_share = round(100.0 * dominant[1] / total, 1) if (dominant and total) else 0.0

    case_key = None
    case_fa = None
    explanation_fa = "در حال حاضر داده‌ها الگوی قطعی نشان نمی‌دهند؛ پایش ادامه یابد."
    if completion_pct is not None and completion_pct <= 20.0 and len(tasks) >= 3:
        case_key = "a"
        case_fa = "حالت الف"
        explanation_fa = (
            f"{round(100 - completion_pct)}٪ دانش‌آموزان تمرین را انجام نداده‌اند — "
            "احتمالاً مسئله صرفاً تدریس نیست؛ مشارکت و انجام تکلیف بررسی شود."
        )
    elif dominant is not None and dominant_share >= 60.0:
        case_key = "b"
        case_fa = "حالت ب"
        explanation_fa = (
            f"تمرین‌ها انجام شده، اما {round(dominant_share)}٪ خطاها یک کج‌فهمی مشترک "
            f"«{dominant[0]}» دارند — نیازمند بررسی آموزشی محتوا/تدریس."
        )
    elif relapsed >= 2 and with_data:
        low_growth = 0
        for st in with_data:
            hist = st.history or []
            if len(hist) >= 2:
                delta = st.effective_mastery - float(hist[0].get("e", hist[0].get("E", st.effective_mastery)))
                if delta < 1.0:
                    low_growth += 1
        if low_growth:
            case_key = "c"
            case_fa = "حالت ج"
            explanation_fa = (
                f"{low_growth} دانش‌آموز عقب‌ماندگی چند آزمونی و رشد کم حتی بعد از مداخله دارند — "
                "هشدار مدیریتی قوی‌تر؛ بررسی حضوری لازم است."
            )

    return {
        "factors": factors,
        "case": case_key,
        "case_fa": case_fa,
        "explanation_fa": explanation_fa,
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

    # §6.1 عوامل + توضیح سه‌حالته (الف/ب/ج) — بدون حذف هیچ‌کدام از کلیدهای قبلی
    extra = await diagnosis_factors(db, class_id)
    if extra["case_fa"]:
        actions.insert(0, f"{extra['case_fa']}: {extra['explanation_fa']}")

    return {
        "class_id": class_id,
        "class_mastery": summary["avg_mastery"],
        "error_causes": causes,
        "total_errors": total,
        "weak_topics": summary["weak_topics"],
        "grounded_actions_fa": actions or ["داده کافی برای تشخیص وجود ندارد"],
        "factors": extra["factors"],
        "case": extra["case"],
        "case_fa": extra["case_fa"],
        "explanation_fa": extra["explanation_fa"],
        "note_fa": "هیچ‌کدام از این نتایج حکم درباره کیفیت تدریس نیست؛ ورودی بررسی مدیریتی است.",
    }


# ==============================================================================
# §14 تحلیل در سطح پایه + §15 نبض مدرسه (چندمحوری، نه یک عدد)
# ==============================================================================


async def grade_analysis(db: AsyncSession, school_id: int, grade: str) -> dict:
    """§14 «پایه دهم را بررسی کن»: تسط/ماندگاری هر درسِ همان پایه در همین
    مدرسه + مباحث بحرانی هر درس (همان رادار مباحث، این‌بار در سطح پایه).
    محدودهٔ درس از روی کتاب همان پایه تعیین می‌شود."""
    classes = [c for c in await _school_classes(db, school_id) if c.grade == grade]
    student_ids = [
        p.user_id
        for p in (
            await db.execute(
                select(StudentProfile).where(StudentProfile.school_id == school_id)
            )
        ).scalars()
        if p.class_id in {c.id for c in classes}
    ]
    if not classes:
        return {
            "school_id": school_id,
            "grade": grade,
            "subjects": [],
            "classes": [],
            "note_fa": "کلاسی برای این پایه در این مدرسه ثبت نشده است.",
        }

    # کتاب‌های این پایه → محدودهٔ مباحث هر درس
    rows = (
        (
            await db.execute(
                select(Topic, Chapter, Book)
                .join(Chapter, Topic.chapter_id == Chapter.id)
                .join(Book, Chapter.book_id == Book.id)
                .where(Book.grade == grade)
            )
        ).all()
        if student_ids
        else []
    )
    by_subject: dict[str, dict[int, list]] = {}
    for topic, _ch, book in rows:
        by_subject.setdefault(book.subject, {}).setdefault(topic.id, [])

    if by_subject and student_ids:
        topic_ids = [tid for m in by_subject.values() for tid in m]
        states = (
            await db.execute(
                select(StudentTopicState).where(
                    StudentTopicState.student_user_id.in_(student_ids),
                    StudentTopicState.topic_id.in_(topic_ids),
                )
            )
        ).scalars().all()
        for st in states:
            bucket = None
            for _subject, topics in by_subject.items():
                if st.topic_id in topics:
                    bucket = topics
                    break
            if bucket is not None:
                bucket[st.topic_id].append(st)

    titles = await _topic_titles(db)
    settings = get_settings()
    subjects_out: list[dict] = []
    for subject, topic_map in sorted(by_subject.items()):
        states_all = [st for sts in topic_map.values() for st in sts]
        with_data = [st for st in states_all if st.evidence_count >= settings.evidence_min_for_status]
        mastery_vals = [st.effective_mastery for st in with_data]
        retention_vals = [st.retention for st in with_data]
        weak_counter: Counter[int] = Counter()
        for st in states_all:
            if status_of(st.effective_mastery, st.evidence_count) in ("critical", "weak"):
                weak_counter[st.topic_id] += 1
        subjects_out.append(
            {
                "subject": subject,
                "avg_mastery": round(sum(mastery_vals) / len(mastery_vals), 1) if mastery_vals else None,
                "avg_retention": round(sum(retention_vals) / len(retention_vals), 3) if retention_vals else None,
                "students_with_data": len({st.student_user_id for st in with_data}),
                "critical_topics": [
                    {"topic_id": tid, "title": titles.get(tid, f"#{tid}"), "students": n}
                    for tid, n in weak_counter.most_common(3)
                ],
            }
        )
    subjects_out.sort(key=lambda r: (r["avg_mastery"] is None, r["avg_mastery"] if r["avg_mastery"] is not None else 0))

    return {
        "school_id": school_id,
        "grade": grade,
        "classes": [{"id": c.id, "name": c.name} for c in classes],
        "subjects": subjects_out,
        "note_fa": "محدودهٔ هر درس از کتاب همان پایه تعیین می‌شود؛ روی هر درس می‌توان مباحث بحرانی همان درس را باز کرد.",
    }


def _axis(key: str, label_fa: str, value, status_fa: str, detail_fa: str, unit: str = "") -> dict:
    return {
        "key": key,
        "label_fa": label_fa,
        "value": value,
        "unit": unit,
        "status_fa": status_fa,
        "detail_fa": detail_fa,
    }


async def school_pulse(db: AsyncSession, school_id: int) -> dict:
    """§15 نبض مدرسه: چند محور مستقل (یادگیری، تسط، ماندگاری، مشارکت،
    ترمیم/عقب‌ماندگی) — هرگز در یک امتیاز ۰ تا ۱۰۰ خلاصه نمی‌شود."""
    settings = get_settings()
    student_ids = [
        p.user_id
        for p in (await db.execute(select(StudentProfile).where(StudentProfile.school_id == school_id))).scalars()
    ]
    states = (
        (await db.execute(select(StudentTopicState).where(StudentTopicState.student_user_id.in_(student_ids)))).scalars()
        if student_ids
        else []
    )
    with_data = [s for s in states if s.evidence_count >= settings.evidence_min_for_status]

    mastery_vals = [s.effective_mastery for s in with_data]
    avg_mastery = round(sum(mastery_vals) / len(mastery_vals), 1) if mastery_vals else None
    retention_vals = [s.retention for s in with_data]
    avg_retention = round(sum(retention_vals) / len(retention_vals), 3) if retention_vals else None

    deltas = [
        s.effective_mastery - float(s.history[0].get("e", s.history[0].get("E", s.effective_mastery)))
        for s in with_data
        if len(s.history or []) >= 2
    ]
    growth = round(sum(deltas) / len(deltas), 1) if deltas else None

    participating = len({s.student_user_id for s in with_data})
    participation_pct = round(100.0 * participating / len(student_ids), 1) if student_ids else None

    status_counts = {"critical": 0, "weak": 0, "consolidating": 0, "mastered": 0, "unknown": 0}
    for s in states:
        status_counts[status_of(s.effective_mastery, s.evidence_count)] += 1
    behind = status_counts["critical"] + status_counts["weak"]
    behind_pct = round(100.0 * behind / len(states), 1) if states else None

    tasks = (
        (await db.execute(select(PlanTask).where(PlanTask.student_user_id.in_(student_ids)))).scalars().all()
        if student_ids
        else []
    )
    completion_pct = (
        round(100.0 * sum(1 for t in tasks if t.status == "done") / len(tasks), 1) if tasks else None
    )

    axes = [
        _axis(
            "learning",
            "یادگیری",
            growth,
            "رو به رشد" if (growth or 0) > 1.0 else ("نیازمند توجه" if (growth is not None and growth < 0) else "ثابت"),
            "تغییر میانگین تسط مؤثر نسبت به نخستین ثبت هر مبحث",
            "واحد",
        ),
        _axis(
            "mastery",
            "تسط",
            avg_mastery,
            "مناسب" if (avg_mastery or 0) >= 65 else ("نیازمند توجه" if avg_mastery is not None else "بدون داده"),
            f"{status_counts['mastered']} مبحث مسلط، {behind} مبحث زیر آستانه",
            "٪",
        ),
        _axis(
            "retention",
            "ماندگاری",
            round(avg_retention * 100, 1) if avg_retention is not None else None,
            "مناسب" if (avg_retention or 0) >= 0.7 else "نیازمند توجه",
            "میانگین ماندگاری مباحث دارای شواهد کافی",
            "٪",
        ),
        _axis(
            "participation",
            "مشارکت",
            participation_pct,
            "مناسب" if (participation_pct or 0) >= 70 else ("عقب‌مانده" if participation_pct is not None else "بدون داده"),
            f"نرخ تکمیل تمرین: {completion_pct if completion_pct is not None else '—'}٪",
            "٪",
        ),
        _axis(
            "repair",
            "ترمیم/عقب‌ماندگی",
            behind,
            "عقب‌مانده" if behind_pct is not None and behind_pct >= 40 else ("نیازمند توجه" if behind else "مناسب"),
            f"{status_counts['critical']} بحرانی و {status_counts['weak']} ضعیف از {len(states)} رکورد مبحث",
            "مورد",
        ),
    ]

    return {
        "school_id": school_id,
        "axes": axes,
        "single_score": None,
        "students": len(student_ids),
        "status_counts": status_counts,
        "note_fa": "نبض مدرسه چندمحوری است و هرگز به یک امتیاز مصنوعی خلاصه نمی‌شود تا واقعیت بیش‌ازحد ساده نشود.",
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
