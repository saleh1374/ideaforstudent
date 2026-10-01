"""نمای عمیق مدیر مدرسه (سند پنل مدیر مدرسه §8 و §13):

- §8 «مقایسه معلم با معلم — با احتیاط»: جدول تسط/رشد/ماندگاری هر کلاسِ هر
  معلم + عوامل زمینه‌ای. اصل «Raw Score ≠ Teacher Quality» رعایت می‌شود:
  عوامل زمینه‌ای نشان داده می‌شوند ولی وزن‌دهی‌شان سیاستی است (طبق ضمیمه
  سند: «تصمیم آماری/سیاستی که نیاز به داده پایلوت دارد») و هیچ امتیاز کلی
  برای معلم ساخته نمی‌شود.
- §13 «نمای فردی دانش‌آموز برای مدیر»: تسط/ماندگاری/رتبه کلاسی/روند +
  خطاها/مباحث بحرانی/تکمیل تمرین + مشکل اصلی + چرخه مداخله + مباحث و
  آزمون‌های اخیر.

سرکوب حداقل جمعیت: هر کلاس زیر MIN_GROUP اعدادش مخفی می‌شود (فقط تعداد)."""
from __future__ import annotations

from collections import Counter, defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.assessment import AttemptAnswer, Exam, ExamAttempt, ExamItem, QuestionItem
from app.models.catalog import Prerequisite
from app.models.org import ClassRoom, ClassTeacherAssignment, StudentProfile, User
from app.models.slm import ErrorRecord, Evidence, PlanTask, StudentTopicState
from app.services.slm import status_of
from app.services.school import (
    CAUSE_SEVERITY_FA,
    MIN_GROUP_FOR_COMPARISON,
    _platform_behavior,
    _states_for_class,
    _topic_titles,
    class_subject_summary,
)

# عوامل زمینه‌ای مقایسه (§8): توضیح فارسی هر کدام برای نمایش در UI
CONTEXT_FACTOR_FA = {
    "baseline_mastery": "سطح اولیه دانش‌آموزان (نخستین ثبت تاریخچه)",
    "students_count": "تعداد دانش‌آموز دارای داده",
    "attendance_pct": "حضور",
    "exam_difficulty_avg": "سختی آزمون‌ها (میانگین وزن دشواری سؤال‌ها)",
    "prereq_weak_ratio": "وضعیت پیش‌نیازها (نسبت پیش‌نیازهای زیر آستانه)",
    "sessions_recorded": "تعداد جلسات آزمون ثبت‌شده",
    "practice_evidence": "میزان تمرین (شواهد تمرینی)",
    "plan_completion_pct": "تکمیل برنامه روزانه",
}

ATTENDANCE_NOTE_FA = (
    "منبع داده حضور هنوز به پلتفرم متصل نیست؛ این ستون عمداً خالی می‌ماند "
    "تا رقم ساختگی گزارش نشود (سند §۸: حضور یکی از عوامل زمینه‌ای است)."
)

RAW_SCORE_NOTE_FA = (
    "Raw Score ≠ Teacher Quality — پیش از هر مقایسه، سطح اولیه دانش‌آموزان، "
    "تعداد دانش‌آموز، حضور، سختی آزمون، وضعیت پیش‌نیازها، تعداد جلسات و میزان "
    "تمرین باید لحاظ شوند؛ مقایسه خام گمراه‌کننده و ناعادلانه است."
)

WEIGHTING_NOTE_FA = (
    "وزن‌دهی عوامل زمینه‌ای هنوز کالیبره نشده (طبق ضمیمه سند: تصمیمی آماری/"
    "سیاستی که به داده پایلوت نیاز دارد)؛ اعداد خام را رتبه‌بندی نکنید."
)


def fa_num(n: float | int) -> str:
    """رقم فارسی ساده برای متن‌های توضیحی."""
    return str(n).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
async def _class_student_ids(db: AsyncSession, class_id: int) -> list[int]:
    rows = (
        await db.execute(select(StudentProfile.user_id).where(StudentProfile.class_id == class_id))
    ).scalars().all()
    return list(rows)


async def _states_of_student(db: AsyncSession, user_id: int) -> list[StudentTopicState]:
    return list(
        (
            await db.execute(
                select(StudentTopicState).where(StudentTopicState.student_user_id == user_id)
            )
        ).scalars()
    )


def _growth_of(states: list[StudentTopicState]) -> float | None:
    """رشد = میانگین (E فعلی − E نخستین ثبت تاریخچه) روی مباحثی که دست‌کم دو
    ثبت دارند؛ بدون تاریخچه کافی → None (نه صفرِ گمراه‌کننده)."""
    deltas = [
        st.effective_mastery - float(st.history[0].get("e", st.effective_mastery))
        for st in states
        if len(st.history or []) >= 2
    ]
    if not deltas:
        return None
    return round(sum(deltas) / len(deltas), 1)


async def _class_context(db: AsyncSession, class_id: int, student_ids: list[int]) -> dict:
    """عوامل زمینه‌ای §8 برای یک کلاس (بدون وزن‌دهی نهایی — سیاستی)."""
    states = await _states_for_class(db, class_id)

    # سطح اولیه: میانگین E نخستین ثبت تاریخچه
    baselines = [float(st.history[0].get("e", st.effective_mastery)) for st in states if st.history]
    baseline = round(sum(baselines) / len(baselines), 1) if baselines else None

    # سختی آزمون‌ها: میانگین difficulty_weight سؤالاتی که همین کلاس پاسخ داده
    difficulty: float | None = None
    if student_ids:
        rows = (
            await db.execute(
                select(QuestionItem.difficulty_weight)
                .join(ExamItem, ExamItem.item_id == QuestionItem.id)
                .join(AttemptAnswer, AttemptAnswer.exam_item_id == ExamItem.id)
                .where(AttemptAnswer.student_user_id.in_(student_ids))
            )
        ).scalars().all()
        if rows:
            difficulty = round(sum(rows) / len(rows), 2)

    # وضعیت پیش‌نیازها: مباحثی که پیش‌نیازِ مبحث دیگری‌اند و زیر آستانه‌اند
    prereq_ids = set((await db.execute(select(Prerequisite.prereq_topic_id))).scalars().all())
    prereq_states = [st for st in states if st.topic_id in prereq_ids]
    prereq_weak = [
        st
        for st in prereq_states
        if status_of(st.effective_mastery, st.evidence_count) in ("weak", "critical")
    ]
    prereq_ratio = round(len(prereq_weak) / len(prereq_states), 3) if prereq_states else None

    # جلسات / تمرین / برنامه
    behavior = await _platform_behavior(db, class_id)
    practice = (
        list(
            (
                await db.execute(
                    select(Evidence.id).where(
                        Evidence.student_user_id.in_(student_ids), Evidence.source == "practice"
                    )
                )
            ).scalars()
        )
        if student_ids
        else []
    )
    task_statuses = (
        list(
            (await db.execute(select(PlanTask.status).where(PlanTask.student_user_id.in_(student_ids)))).scalars()
        )
        if student_ids
        else []
    )
    plan_pct = (
        round(100.0 * sum(1 for s in task_statuses if s == "done") / len(task_statuses), 1)
        if task_statuses
        else None
    )

    return {
        "baseline_mastery": baseline,
        "students_count": len(student_ids),
        # حضور: داده موجود نیست → null + توضیح (هرگز رقم ساختگی)
        "attendance_pct": None,
        "exam_difficulty_avg": difficulty,
        "prereq_weak_ratio": prereq_ratio,
        "sessions_recorded": behavior["exam_sessions_recorded"],
        "practice_evidence": len(practice),
        "plan_completion_pct": plan_pct,
        "factor_labels_fa": CONTEXT_FACTOR_FA,
        "attendance_note_fa": ATTENDANCE_NOTE_FA,
    }


# --------------------------------------------------------------------------- #
# §8 مقایسه معلم با معلم
# --------------------------------------------------------------------------- #
async def teacher_comparison(db: AsyncSession, school_id: int, subject: str) -> dict:
    classes = (await db.execute(select(ClassRoom).where(ClassRoom.school_id == school_id))).scalars().all()

    rows: list[dict] = []
    for cls in classes:
        link = (
            (
                await db.execute(
                    select(ClassTeacherAssignment).where(
                        ClassTeacherAssignment.class_id == cls.id,
                        ClassTeacherAssignment.subject == subject,
                        ClassTeacherAssignment.status == "active",
                    )
                )
            )
            .scalars()
            .first()
        )
        if link is None:
            continue

        student_ids = await _class_student_ids(db, cls.id)
        summary = await class_subject_summary(db, cls.id)
        states = await _states_for_class(db, cls.id)
        teacher = await db.get(User, link.teacher_user_id)

        suppressed = summary["students_with_data"] < MIN_GROUP_FOR_COMPARISON
        growth = _growth_of(states)
        context = await _class_context(db, cls.id, student_ids)

        rows.append(
            {
                "class_id": cls.id,
                "class_name": cls.name,
                "grade": cls.grade,
                "subject": subject,
                "teacher_id": link.teacher_user_id,
                "teacher_name": teacher.full_name if teacher else None,
                "students_with_data": summary["students_with_data"],
                # زیر حداقل جمعیت → اعداد مخفی؛ فقط ساختار ردیف می‌ماند
                "mastery": None if suppressed else summary["avg_mastery"],
                "retention": None if suppressed else summary["avg_retention"],
                "growth": None if suppressed else growth,
                "total_errors": summary["total_errors"],
                "weak_topics": summary["weak_topics"],
                "suppressed": suppressed,
                "context": context,
            }
        )

    rows.sort(key=lambda r: (r["mastery"] if r["mastery"] is not None else 999))

    # تجمیع در سطح معلم («مقایسه معلم-به-معلم») — بدون امتیاز کلی
    by_teacher: dict[int, dict] = {}
    for r in rows:
        bucket = by_teacher.setdefault(
            r["teacher_id"],
            {
                "teacher_id": r["teacher_id"],
                "teacher_name": r["teacher_name"],
                "classes": [],
                "_m": [],
                "_r": [],
                "_g": [],
                "_students": 0,
            },
        )
        bucket["classes"].append(
            {"class_id": r["class_id"], "class_name": r["class_name"], "suppressed": r["suppressed"]}
        )
        if not r["suppressed"]:
            bucket["_students"] += r["students_with_data"]
            if r["mastery"] is not None:
                bucket["_m"].append(r["mastery"])
            if r["retention"] is not None:
                bucket["_r"].append(r["retention"])
            if r["growth"] is not None:
                bucket["_g"].append(r["growth"])

    teachers = [
        {
            "teacher_id": b["teacher_id"],
            "teacher_name": b["teacher_name"],
            "classes_count": len(b["classes"]),
            "classes": b["classes"],
            "avg_mastery": round(sum(b["_m"]) / len(b["_m"]), 1) if b["_m"] else None,
            "avg_retention": round(sum(b["_r"]) / len(b["_r"]), 3) if b["_r"] else None,
            "avg_growth": round(sum(b["_g"]) / len(b["_g"]), 1) if b["_g"] else None,
            "students_with_data": b["_students"],
            "suppressed": not b["_m"],
        }
        for b in by_teacher.values()
    ]
    teachers.sort(key=lambda t: (t["avg_mastery"] if t["avg_mastery"] is not None else 999))

    visible = [r for r in rows if not r["suppressed"]]
    return {
        "school_id": school_id,
        "subject": subject,
        "comparison_valid": len(visible) >= 2,
        "min_group": MIN_GROUP_FOR_COMPARISON,
        "min_group_note": (
            f"مقایسه معنادار فقط با حداقل {MIN_GROUP_FOR_COMPARISON} دانش‌آموز "
            "دارای داده در هر کلاس؛ کلاس‌های کوچک‌تر مخفی می‌شوند."
        ),
        "raw_score_note_fa": RAW_SCORE_NOTE_FA,
        "weighting_note_fa": WEIGHTING_NOTE_FA,
        "rows": rows,
        "teachers": teachers,
    }


# --------------------------------------------------------------------------- #
# §13 نمای فردی دانش‌آموز
# --------------------------------------------------------------------------- #
async def _student_rank(
    db: AsyncSession, profile: StudentProfile
) -> tuple[int | None, int | None]:
    """رتبه دانش‌آموز بین هم‌کلاسی‌ها بر اساس میانگین E — فقط برای مدیر همان
    مدرسه (نه برد عمومی)."""
    if profile.class_id is None:
        return None, None
    mates = list(
        (
            await db.execute(
                select(StudentProfile.user_id).where(StudentProfile.class_id == profile.class_id)
            )
        ).scalars()
    )
    if not mates:
        return None, None

    all_states = (
        await db.execute(select(StudentTopicState).where(StudentTopicState.student_user_id.in_(mates)))
    ).scalars().all()
    per_user: dict[int, list[float]] = defaultdict(list)
    for st in all_states:
        if st.evidence_count > 0:
            per_user[st.student_user_id].append(st.effective_mastery)

    def avg(vals: list[float]) -> float:
        return sum(vals) / len(vals) if vals else -1.0

    mine = avg(per_user.get(profile.user_id, []))
    if mine < 0:
        return None, len(per_user) or None
    rank = 1 + sum(
        1 for uid, vals in per_user.items() if uid != profile.user_id and avg(vals) > mine
    )
    return rank, len(per_user)


async def student_detail(db: AsyncSession, school_id: int, user_id: int) -> dict:
    profile = (
        (
            await db.execute(
                select(StudentProfile).where(
                    StudentProfile.user_id == user_id, StudentProfile.school_id == school_id
                )
            )
        )
        .scalars()
        .first()
    )
    if profile is None:
        raise LookupError("student_not_in_school")

    settings = get_settings()
    student = await db.get(User, user_id)
    cls = await db.get(ClassRoom, profile.class_id) if profile.class_id else None
    titles = await _topic_titles(db)

    states = await _states_of_student(db, user_id)
    with_data = [st for st in states if st.evidence_count >= settings.evidence_min_for_status]

    mastery_vals = [st.effective_mastery for st in with_data]
    retention_vals = [st.retention for st in with_data]
    overall = round(sum(mastery_vals) / len(mastery_vals), 1) if mastery_vals else None
    retention = round(sum(retention_vals) / len(retention_vals), 3) if retention_vals else None

    # روند: میانگین ΔE روی مباحث با دست‌کم دو ثبت تاریخچه
    deltas = [
        st.effective_mastery - float(st.history[0].get("e", st.effective_mastery))
        for st in states
        if len(st.history or []) >= 2
    ]
    if deltas:
        trend_delta = round(sum(deltas) / len(deltas), 1)
        trend = "up" if trend_delta > 0.5 else "down" if trend_delta < -0.5 else "flat"
    else:
        trend_delta, trend = None, "unknown"

    rank, class_size = await _student_rank(db, profile)

    # خطاها
    errors = (await db.execute(select(ErrorRecord).where(ErrorRecord.student_user_id == user_id))).scalars().all()
    open_errors = [e for e in errors if e.status in ("open", "in_remediation", "relapsed")]
    resolved = sum(1 for e in errors if e.status == "resolved")
    relapsed = sum(1 for e in errors if e.status == "relapsed")
    causes = Counter(e.cause for e in open_errors)
    dominant = causes.most_common(1)[0] if causes else None

    critical = [
        st for st in with_data if status_of(st.effective_mastery, st.evidence_count) in ("weak", "critical")
    ]

    # تکمیل تمرین (برنامه روزانه)
    task_statuses = list(
        (await db.execute(select(PlanTask.status).where(PlanTask.student_user_id == user_id))).scalars()
    )
    practice_pct = (
        round(100.0 * sum(1 for s in task_statuses if s == "done") / len(task_statuses), 1)
        if task_statuses
        else None
    )

    # چرخه مداخله: resolve/relapse خودِ چرخه‌های ترمیم–بازآزمون هستند
    cycles = resolved + relapsed
    if cycles == 0:
        result_fa = "هنوز مداخله‌ای ثبت نشده است."
    elif relapsed >= resolved and relapsed > 0:
        result_fa = (
            f"{fa_num(cycles)} چرخه؛ مداخله بی‌اثر بوده "
            f"(بازگشت {fa_num(relapsed)} ≥ رفع {fa_num(resolved)}) — بازبینی شود."
        )
    else:
        result_fa = (
            f"{fa_num(cycles)} چرخه؛ نتیجه مثبت ({fa_num(resolved)} رفع‌شده، {fa_num(relapsed)} بازگشت)."
        )

    main_problem = (
        f"بیشتر خطاهای باز مربوط به «{CAUSE_SEVERITY_FA.get(dominant[0], dominant[0])}» است "
        f"({fa_num(dominant[1])} مورد)."
        if dominant
        else "خطای بازی ثبت نشده است."
    )

    answers = (
        (await db.execute(select(AttemptAnswer).where(AttemptAnswer.student_user_id == user_id))).scalars().all()
    )
    behavior = {
        "exam_sessions_recorded": len({a.attempt_id for a in answers}),
        "answers_recorded": len(answers),
    }

    # مباحث (پررنگ‌ترین اول)
    order = {"critical": 0, "weak": 1, "unknown": 2, "consolidating": 3, "mastered": 4}
    topic_rows = sorted(
        states, key=lambda st: order.get(status_of(st.effective_mastery, st.evidence_count), 9)
    )
    topics = [
        {
            "topic_id": st.topic_id,
            "title": titles.get(st.topic_id, f"#{st.topic_id}"),
            "mastery": round(st.effective_mastery, 1),
            "retention": round(st.retention, 3),
            "status": status_of(st.effective_mastery, st.evidence_count),
            "evidence_count": st.evidence_count,
        }
        for st in topic_rows
    ]

    # آزمون‌های اخیر
    attempts = (
        (
            await db.execute(
                select(ExamAttempt)
                .where(ExamAttempt.student_user_id == user_id)
                .order_by(ExamAttempt.submitted_at.desc(), ExamAttempt.id.desc())
                .limit(10)
            )
        )
        .scalars()
        .all()
    )
    recent: list[dict] = []
    for a in attempts:
        ans = (await db.execute(select(AttemptAnswer).where(AttemptAnswer.attempt_id == a.id))).scalars().all()
        exam = await db.get(Exam, a.exam_id)
        recent.append(
            {
                "attempt_id": a.id,
                "exam_id": a.exam_id,
                "exam_title": exam.title_fa if exam else None,
                "subject": exam.subject if exam else None,
                "percent": round(a.percent, 1) if a.percent is not None else None,
                "raw_score": a.raw_score,
                "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None,
                "correct": sum(1 for x in ans if x.is_correct),
                "wrong": sum(1 for x in ans if not x.is_correct and x.selected_option),
                "blank": sum(1 for x in ans if not x.selected_option),
                "avg_time_ms": round(sum(x.time_spent_ms for x in ans) / len(ans)) if ans else None,
            }
        )

    return {
        "student": {
            "user_id": user_id,
            "full_name": student.full_name if student else None,
            "username": student.username if student else None,
            "grade": profile.grade,
            "class_id": profile.class_id,
            "class_name": cls.name if cls else None,
            "status": profile.status,
        },
        "mastery": {
            "overall": overall,
            "retention": retention,
            "rank_in_class": rank,
            "class_size": class_size,
            "trend": trend,
            "trend_delta": trend_delta,
        },
        "indicators": {
            "repeat_open_errors": len(open_errors),
            "critical_topics": len(critical),
            "practice_completion_pct": practice_pct,
            "attendance_pct": None,
            "attendance_note_fa": ATTENDANCE_NOTE_FA,
            "platform": behavior,
        },
        "error_causes": dict(causes),
        "main_problem_fa": main_problem,
        "interventions": {"cycles": cycles, "resolved": resolved, "relapsed": relapsed, "result_fa": result_fa},
        "topics": topics,
        "recent_attempts": recent,
        "note_fa": (
            "نمای فردی برای بررسی مدیریتی است؛ رتبه فقط داخل کلاس خودِ دانش‌آموز "
            "محاسبه می‌شود و در هیچ برد عمومی نمایش داده نمی‌شود."
        ),
    }


# --------------------------------------------------------------------------- #
# فهرست دانش‌آموزان مدرسه (برای انتخابگر UI)
# --------------------------------------------------------------------------- #
async def list_students(db: AsyncSession, school_id: int) -> dict:
    profiles = (
        (
            await db.execute(
                select(StudentProfile)
                .where(StudentProfile.school_id == school_id)
                .order_by(StudentProfile.class_id, StudentProfile.user_id)
            )
        )
        .scalars()
        .all()
    )
    classes = {
        c.id: c.name
        for c in (await db.execute(select(ClassRoom).where(ClassRoom.school_id == school_id))).scalars().all()
    }

    rows: list[dict] = []
    for p in profiles:
        user = await db.get(User, p.user_id)
        states = await _states_of_student(db, p.user_id)
        with_data = [st for st in states if st.evidence_count >= get_settings().evidence_min_for_status]
        vals = [st.effective_mastery for st in with_data]
        rows.append(
            {
                "user_id": p.user_id,
                "full_name": user.full_name if user else None,
                "username": user.username if user else None,
                "class_id": p.class_id,
                "class_name": classes.get(p.class_id),
                "avg_mastery": round(sum(vals) / len(vals), 1) if vals else None,
            }
        )
    return {"school_id": school_id, "total": len(rows), "students": rows}
