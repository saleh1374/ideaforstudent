"""گزارش‌های پنل والدین — سند پنل والدین §3 (گزارش آزمون‌ها)، §6 (برنامه فقط‌خواندنی)،
§13 (هشدارهای هوشمند) و §14 (گزارش هفتگی).

قواعد سراسری این ماژول:
* خروجی فقط از داده‌های «همان فرزند» ساخته می‌شود — بدون رتبه، بدون رتبه‌بندی و
  بدون مقایسه با دانش‌آموزان دیگر (حریم خصوصی کودک، سند والدین §16).
* هشدارها قاعده‌محور و قطعی‌اند (هیچ مدل بیرونی در کار نیست)؛ آستانه‌های تسط از
  `Settings` می‌آید و ثابت‌های رفتاری همین ماژول است تا قابل تنظیم بماند.
* لحن هشدارها آرام و همراه با یک اقدام مشخص و قابل‌انجام (سند §13)."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.models.assessment import AttemptAnswer, Exam, ExamAttempt, ExamItem, QuestionItem
from app.models.catalog import Book, Chapter, Topic
from app.models.org import StudentProfile, User
from app.models.parent_panel import ParentMeeting, SchoolAttendance
from app.models.slm import ErrorRecord, Evidence, PlanTask, StudentTopicState
from app.services.slm import status_of

# ---- ثابت‌های قاعده‌ی هشدار (آستانه‌های تسط از Settings می‌آید) ----
GAP_ALERT_UNITS = 15.0          # سند §5/§1: شکاف پیشرفت برنامه ↔ تسط واقعی
INACTIVE_DAYS = 7               # «بدون فعالیت» = بیش از این تعداد روز بدون شاهد
REPEAT_ERROR_MIN = 2            # حداقل تکرار یک خطا برای «خطای تکراری حل‌نشده»
POSITIVE_DELTA_PCT = 5.0        # حداقل بهبود درصد برای هشدار مثبت «پیشرفت»
INTERVENTION_EPSILON = 2.0      # کمتر از این تغییر E بعد از ۲ شاهد ⇒ «مداخله مؤثر نبود»
MAX_ALERTS = 12                 # سقف هشدار (جلوگیری از خستگی اعلان — ضمیمه ج)
MAX_REPEAT_ERROR_ALERTS = 3
MAX_WEAK_TOPIC_ALERTS = 3
MAX_RETENTION_ALERTS = 2
MAX_INTERVENTION_ALERTS = 2

SEVERITY_RANK = {"danger": 0, "warning": 1, "info": 2}

# هدف تسط دوره برای «نسبت به هدف دوره» (سند §4) — یک برنامه‌ریزی، نه نمره‌ی دیگران
PERIOD_GOAL_MASTERY = 70.0

CAUSE_FA = {
    "conceptual": "مفهومی",
    "prerequisite": "پیش‌نیاز",
    "calculation": "محاسباتی",
    "careless": "بی‌دقتی",
    "time_management": "زمان",
    "guess": "حدس",
}

NOTE_NO_RANK = (
    "این گزارش فقط از داده‌های فرزند شما ساخته شده است؛ بدون رتبه و بدون مقایسه "
    "با دانش‌آموزان دیگر."
)
NOTE_PLAN_READONLY = (
    "نمای فقط‌خواندنی برنامه؛ تغییر برنامه یا SLM فقط از موتور برنامه‌ریز و معلم "
    "انجام می‌شود (سند والدین §6)."
)


# ------------------------------------------------------------------ helpers


def _naive_utc(dt: datetime | None) -> datetime | None:
    """همه‌ی زمان‌های خوانده‌شده از ستون‌ها naive-utc هستند؛ همگراسی برای مقایسه."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _iso(dt: datetime | None) -> str | None:
    n = _naive_utc(dt)
    return n.isoformat() if n else None


async def _topics_map(db: AsyncSession) -> dict[int, Topic]:
    return {t.id: t for t in (await db.execute(select(Topic))).scalars()}


async def _states_of(db: AsyncSession, student_id: int) -> list[StudentTopicState]:
    return list(
        (
            await db.execute(
                select(StudentTopicState).where(StudentTopicState.student_user_id == student_id)
            )
        ).scalars()
    )


async def _tasks_of(db: AsyncSession, student_id: int) -> list[PlanTask]:
    return list(
        (
            await db.execute(
                select(PlanTask)
                .where(PlanTask.student_user_id == student_id)
                .order_by(PlanTask.for_date, PlanTask.priority.desc())
            )
        ).scalars()
    )


async def _open_errors_of(db: AsyncSession, student_id: int) -> list[ErrorRecord]:
    """خطاهای حل‌نشده: باز / در چرخه ترمیم / بازگشته (همان تعریف overview)."""
    return list(
        (
            await db.execute(
                select(ErrorRecord)
                .where(
                    ErrorRecord.student_user_id == student_id,
                    ErrorRecord.status.in_(["open", "in_remediation", "relapsed"]),
                )
                .order_by(ErrorRecord.created_at.desc())
            )
        ).scalars()
    )


async def _graded_attempts(db: AsyncSession, student_id: int) -> list[ExamAttempt]:
    return list(
        (
            await db.execute(
                select(ExamAttempt)
                .where(
                    ExamAttempt.student_user_id == student_id,
                    ExamAttempt.submitted_at.is_not(None),
                )
                .order_by(ExamAttempt.submitted_at.asc(), ExamAttempt.id.asc())
            )
        ).scalars()
    )


async def progress_mastery(db: AsyncSession, student_id: int) -> dict:
    """پیشرفت برنامه ↔ تسط واقعی — همان دو شاخصِ overview، برای استفاده مجدد."""
    states = await _states_of(db, student_id)
    topics = await _topics_map(db)

    num = den = 0.0
    for st in states:
        t = topics.get(st.topic_id)
        w = (t.blueprint_weight if t else 1.0) or 1.0
        num += w * st.effective_mastery
        den += w
    mastery_pct = round(num / den, 1) if den else 0.0

    tasks = await _tasks_of(db, student_id)
    done = sum(1 for t in tasks if t.status == "done")
    progress_pct = round(100.0 * done / len(tasks), 1) if tasks else 0.0

    status_counts = {"mastered": 0, "consolidating": 0, "weak": 0, "critical": 0, "unknown": 0}
    for st in states:
        k = status_of(st.effective_mastery, st.evidence_count)
        status_counts[k] = status_counts.get(k, 0) + 1

    return {
        "progress_pct": progress_pct,
        "mastery_pct": mastery_pct,
        "gap": round(progress_pct - mastery_pct, 1),
        "status_counts": status_counts,
        "states": states,
        "topics": topics,
        "tasks": tasks,
    }


# ------------------------------------------------------------------ §3 آزمون‌ها


async def _exam_context(db: AsyncSession, exam_ids: set[int]) -> tuple[dict, dict, dict]:
    """آزمون‌ها + امتیاز هر سؤال + تعداد سؤال هر آزمون (یک‌جا، بدون N+1)."""
    if not exam_ids:
        return {}, {}, {}
    exams = {e.id: e for e in (await db.execute(select(Exam).where(Exam.id.in_(exam_ids)))).scalars()}
    points: dict[int, dict[int, float]] = {}
    for exam_id, item_id, pts in (
        await db.execute(select(ExamItem.exam_id, ExamItem.id, ExamItem.points).where(ExamItem.exam_id.in_(exam_ids)))
    ).all():
        points.setdefault(exam_id, {})[item_id] = pts
    totals = {eid: len(v) for eid, v in points.items()}
    return exams, points, totals


async def exam_results(db: AsyncSession, student_id: int) -> dict:
    """نمره، درصد، صحیح/غلط/نزده، نمره منفی، زمان و روند هر آزمون رسمی (§3)."""
    attempts = await _graded_attempts(db, student_id)
    exams, points, totals = await _exam_context(db, {a.exam_id for a in attempts})

    answers_by_attempt: dict[int, list[AttemptAnswer]] = {}
    if attempts:
        rows = (
            await db.execute(
                select(AttemptAnswer).where(
                    AttemptAnswer.attempt_id.in_([a.id for a in attempts])
                )
            )
        ).scalars()
        for ans in rows:
            answers_by_attempt.setdefault(ans.attempt_id, []).append(ans)

    out: list[dict] = []
    prev_percent: float | None = None
    for a in attempts:
        exam = exams.get(a.exam_id)
        ans = answers_by_attempt.get(a.id, [])
        pmap = points.get(a.exam_id, {})

        correct = sum(1 for x in ans if x.is_correct == 1)
        blank = sum(1 for x in ans if x.selected_option is None)
        wrong = sum(1 for x in ans if x.selected_option is not None and x.is_correct != 1)
        total_items = totals.get(a.exam_id, len(ans))
        blank += max(0, total_items - len(ans))  # سؤال‌های بدون ردیف پاسخ

        k = (exam.negative_marking_k if exam else 0.0) or 0.0
        points_lost = 0.0
        if k > 0 and wrong:
            points_lost = round(
                k * sum(pmap.get(x.exam_item_id, 1.0) for x in ans if x.selected_option is not None and x.is_correct != 1),
                2,
            )

        percent = a.percent
        delta = None
        if percent is not None and prev_percent is not None:
            delta = round(percent - prev_percent, 2)

        out.append(
            {
                "attempt_id": a.id,
                "exam_id": a.exam_id,
                "title": exam.title_fa if exam else f"آزمون #{a.exam_id}",
                "exam_type": exam.exam_type if exam else None,
                "subject": exam.subject if exam else None,
                "grade": exam.grade if exam else None,
                "attempt_status": a.status,
                "score": a.raw_score,
                "percent": percent,
                "delta": delta,
                "correct": correct,
                "wrong": wrong,
                "blank": blank,
                "total": total_items,
                "negative_marking": {"enabled": k > 0, "k": k, "points_lost": points_lost},
                "time_spent_seconds": round(sum((x.time_spent_ms or 0) for x in ans) / 1000.0, 1),
                "started_at": _iso(a.started_at),
                "submitted_at": _iso(a.submitted_at),
            }
        )
        if percent is not None:
            prev_percent = percent

    percents = [x["percent"] for x in out if x["percent"] is not None]
    return {
        "student_id": student_id,
        "exams": out,
        "trend": percents,
        "summary": {
            "count": len(out),
            "avg_percent": round(sum(percents) / len(percents), 1) if percents else None,
            "best_percent": max(percents) if percents else None,
            "latest_percent": percents[-1] if percents else None,
            "negative_marking_exams": len({x["exam_id"] for x in out if x["negative_marking"]["enabled"]}),
            "total_time_seconds": round(sum(x["time_spent_seconds"] for x in out), 1),
        },
        "note_fa": NOTE_NO_RANK,
    }


async def exam_result_detail(db: AsyncSession, student_id: int, attempt_id: int) -> dict:
    """جزئیات یک نتیجه: وضعیت هر درس/مبحث، نوع خطاها و سؤال‌های نادرست (§3)."""
    attempt = (
        await db.execute(
            select(ExamAttempt)
            .where(ExamAttempt.id == attempt_id, ExamAttempt.student_user_id == student_id)
        )
    ).scalar_one_or_none()
    if attempt is None:
        raise LookupError("نتیجه این آزمون برای این فرزند یافت نشد")

    exam = await db.get(Exam, attempt.exam_id)
    items = {
        ei.id: ei
        for ei in (
            await db.execute(
                select(ExamItem)
                .options(selectinload(ExamItem.item))
                .where(ExamItem.exam_id == attempt.exam_id)
            )
        ).scalars()
    }
    answers = list(
        (
            await db.execute(select(AttemptAnswer).where(AttemptAnswer.attempt_id == attempt.id))
        ).scalars()
    )
    topics = await _topics_map(db)

    # وضعیت هر مبحث در این آزمون
    by_topic: dict[int, dict] = {}
    causes: dict[str, int] = {}
    wrong_items: list[dict] = []
    correct = blank = wrong = 0
    for ans in answers:
        ei = items.get(ans.exam_item_id)
        q = ei.item if ei else None
        topic_id = q.topic_id if q else None
        row = by_topic.setdefault(topic_id, {"topic_id": topic_id, "total": 0, "correct": 0, "wrong": 0, "blank": 0})
        row["total"] += 1
        if ans.is_correct == 1:
            correct += 1
            row["correct"] += 1
        elif ans.selected_option is None:
            blank += 1
            row["blank"] += 1
        else:
            wrong += 1
            row["wrong"] += 1
            cause = ans.error_cause or "conceptual"
            causes[cause] = causes.get(cause, 0) + 1
            if len(wrong_items) < 30:
                wrong_items.append(
                    {
                        "position": ans.question_position,
                        "topic_id": topic_id,
                        "topic": topics.get(topic_id).title_fa if topic_id in topics else None,
                        "body": q.body if q else None,
                        "selected": ans.selected_option,
                        "correct": q.correct_option if q else None,
                        "cause": cause,
                        "cause_fa": CAUSE_FA.get(cause, cause),
                    }
                )

    total_items = len(items)
    blank += max(0, total_items - len(answers))

    topic_rows = []
    for topic_id, row in by_topic.items():
        t = topics.get(topic_id)
        row["topic"] = t.title_fa if t else None
        row["percent"] = round(100.0 * row["correct"] / row["total"], 1) if row["total"] else 0.0
        topic_rows.append(row)
    topic_rows.sort(key=lambda r: (r["percent"], -r["wrong"]))

    k = (exam.negative_marking_k if exam else 0.0) or 0.0
    pmap = {ei.id: ei.points for ei in items.values()}
    points_lost = (
        round(k * sum(pmap.get(a.exam_item_id, 1.0) for a in answers if a.selected_option is not None and a.is_correct != 1), 2)
        if k > 0
        else 0.0
    )

    return {
        "student_id": student_id,
        "attempt_id": attempt.id,
        "exam": {
            "id": attempt.exam_id,
            "title": exam.title_fa if exam else f"آزمون #{attempt.exam_id}",
            "exam_type": exam.exam_type if exam else None,
            "subject": exam.subject if exam else None,
            "grade": exam.grade if exam else None,
        },
        "score": attempt.raw_score,
        "percent": attempt.percent,
        "correct": correct,
        "wrong": wrong,
        "blank": blank,
        "total": total_items,
        "negative_marking": {"enabled": k > 0, "k": k, "points_lost": points_lost},
        "time_spent_seconds": round(sum((a.time_spent_ms or 0) for a in answers) / 1000.0, 1),
        "started_at": _iso(attempt.started_at),
        "submitted_at": _iso(attempt.submitted_at),
        "topics": topic_rows,
        "error_causes": [
            {"cause": c, "cause_fa": CAUSE_FA.get(c, c), "count": n}
            for c, n in sorted(causes.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "wrong_items": wrong_items,
        "note_fa": NOTE_NO_RANK,
    }


# ------------------------------------------------------------------ §6 برنامه و تکالیف


async def plan_view(db: AsyncSession, student_id: int) -> dict:
    """برنامه/تکلیف فرزند فقط‌خواندنی + موعدها + بازه‌ی آزمون پیش رو (§6، §8)."""
    s = get_settings()
    now = datetime.utcnow()
    today = date.today()

    tasks = await _tasks_of(db, student_id)
    topics = await _topics_map(db)

    done = sum(1 for t in tasks if t.status == "done")
    pending = sum(1 for t in tasks if t.status == "pending")
    missed = sum(1 for t in tasks if t.status == "missed")
    moved = sum(1 for t in tasks if t.status == "moved")
    due_today = [t for t in tasks if t.for_date == today and t.status != "done"]
    overdue = [t for t in tasks if t.for_date < today and t.status in ("pending", "missed")]

    def bucket(t: PlanTask) -> int:
        if t.for_date < today and t.status in ("pending", "missed"):
            return 0
        if t.for_date == today and t.status != "done":
            return 1
        if t.status != "done":
            return 2
        return 3

    ordered = sorted(tasks, key=lambda t: (bucket(t), t.for_date, -t.priority))
    task_rows = [
        {
            "id": t.id,
            "task_type": t.task_type,
            "topic_id": t.topic_id,
            "topic": topics.get(t.topic_id).title_fa if t.topic_id in topics else None,
            "for_date": t.for_date.isoformat(),
            "priority": t.priority,
            "status": t.status,
            "minicheck_passed": bool(t.minicheck_passed),
            "due": bucket(t) in (0, 1),
            "overdue": bucket(t) == 0,
        }
        for t in ordered[:80]
    ]

    # بازه آزمون پیش رو: آزمون‌های منتشرشده‌ای که هنوز بسته نشده‌اند
    upcoming = (
        (
            await db.execute(
                select(Exam)
                .where(Exam.status == "published")
                .order_by(Exam.opens_at.asc())
                .limit(5)
            )
        )
        .scalars()
        .all()
    )
    exam_rows = []
    for e in upcoming:
        closes = _naive_utc(e.closes_at)
        opens = _naive_utc(e.opens_at)
        if closes is not None and closes < now:
            continue
        days_left = int((closes - now).total_seconds() // 86400) + 1 if closes else None
        exam_rows.append(
            {
                "id": e.id,
                "title": e.title_fa,
                "exam_type": e.exam_type,
                "subject": e.subject,
                "opens_at": _iso(e.opens_at),
                "closes_at": _iso(e.closes_at),
                "days_left": days_left,
                "is_open": bool(opens is not None and opens <= now),
            }
        )

    return {
        "student_id": student_id,
        "summary": {
            "total": len(tasks),
            "done": done,
            "pending": pending,
            "missed": missed,
            "moved": moved,
            "due_today": len(due_today),
            "overdue": len(overdue),
            "progress_pct": round(100.0 * done / len(tasks), 1) if tasks else 0.0,
            "min_group": s.min_group_size,
        },
        "tasks": task_rows,
        "upcoming_exams": exam_rows,
        "next_exam": exam_rows[0] if exam_rows else None,
        "note_fa": NOTE_PLAN_READONLY,
    }


# ------------------------------------------------------------------ §13 هشدارها


def _alert(code: str, severity: str, title: str, message: str, action: str, topic_id: int | None = None) -> dict:
    return {
        "code": code,
        "severity": severity,
        "title": title,
        "message": message,
        "action": action,
        "topic_id": topic_id,
    }


async def build_alerts(db: AsyncSession, student_id: int) -> list[dict]:
    """هشدارهای قاعده‌محور والد (سند §13) — فقط سیگنال‌های خودِ فرزند.

    بدون رتبه، بدون مقایسه با دیگران و بدون قضاوت شخصیتی؛ هر هشدار حتماً
    یک اقدام پیشنهادی مشخص دارد."""
    s = get_settings()
    now = datetime.utcnow()
    today = date.today()

    pm = await progress_mastery(db, student_id)
    states: list[StudentTopicState] = pm["states"]
    topics: dict[int, Topic] = pm["topics"]
    tasks: list[PlanTask] = pm["tasks"]

    open_errors = await _open_errors_of(db, student_id)
    attempts = await _graded_attempts(db, student_id)
    evidences = list(
        (
            await db.execute(
                select(Evidence.occurred_at)
                .where(Evidence.student_user_id == student_id)
                .order_by(Evidence.occurred_at.desc())
                .limit(200)
            )
        ).scalars()
    )

    alerts: list[dict] = []

    # ۱) فعالیت اخیر: بدون فعالیت یا کاهش مشارکت
    ev_times = [t for t in (_naive_utc(x) for x in evidences) if t is not None]
    if not ev_times:
        if tasks:
            alerts.append(
                _alert(
                    "no_activity",
                    "warning",
                    "هنوز فعالیتی ثبت نشده است",
                    "برای این فرزند شاهد یادگیری ثبت نشده و برنامه نیز اجرا نشده است.",
                    "امروز اولین کار برنامه را با یک مرور کوتاه ۲۰ دقیقه‌ای آغاز کنید.",
                )
            )
    else:
        idle_days = (now - max(ev_times)).total_seconds() / 86400.0
        if idle_days >= INACTIVE_DAYS:
            alerts.append(
                _alert(
                    "inactivity",
                    "warning",
                    "کاهش فعالیت اخیر",
                    f"حدود {int(idle_days)} روز است که فعالیت آموزشی جدیدی ثبت نشده است.",
                    "یک جلسه مرور کوتاه و یک کار عقب‌افتاده‌ی برنامه برای امروز مشخص کنید.",
                )
            )

    # ۲) شکاف پیشرفت برنامه ↔ تسط واقعی (سند §5)
    gap = pm["gap"]
    if abs(gap) >= GAP_ALERT_UNITS:
        if gap > 0:
            alerts.append(
                _alert(
                    "progress_gap",
                    "warning",
                    "شکاف میان پیشرفت برنامه و یادگیری تثبیت‌شده",
                    f"پیشرفت برنامه {pm['progress_pct']}٪ ولی تسط واقعی {pm['mastery_pct']}٪ است "
                    f"(شکاف {abs(gap)} واحد).",
                    "به‌جای افزودن مطلب جدید، مرور فاصله‌دار و بسته ترمیمی اولویت دارد.",
                )
            )
        else:
            alerts.append(
                _alert(
                    "progress_gap",
                    "warning",
                    "عقب‌ماندگی برنامه نسبت به تسلط",
                    f"تسط واقعی {pm['mastery_pct']}٪ است ولی فقط {pm['progress_pct']}٪ برنامه انجام شده "
                    f"(شکاف {abs(gap)} واحد).",
                    "سرعت پیشروی در برنامه بررسی شود و کارهای معوقه امروز مشخص شوند.",
                )
            )

    # ۳) کارهای عقب‌افتاده (سند §8)
    overdue = [t for t in tasks if t.for_date < today and t.status in ("pending", "missed")]
    if overdue:
        alerts.append(
            _alert(
                "overdue_tasks",
                "warning",
                "کارهای عقب‌افتاده‌ی برنامه",
                f"{len(overdue)} کار برنامه موعدشان گذشته و هنوز انجام نشده است.",
                "برای امشب فقط یکی از کارهای عقب‌افتاده انتخاب شود تا فشار روزانه زیاد نشود.",
            )
        )

    # ۴) خطای تکراری حل‌نشده (سند §6 دفترچه خطا)
    repeated: dict[tuple[int | None, str], int] = {}
    for e in open_errors:
        repeated[(e.topic_id, e.cause)] = repeated.get((e.topic_id, e.cause), 0) + 1
    repeated_sorted = sorted(
        ((k, n) for k, n in repeated.items() if n >= REPEAT_ERROR_MIN),
        key=lambda kv: (-kv[1], kv[0][0] or 0, kv[0][1]),
    )[:MAX_REPEAT_ERROR_ALERTS]
    for (topic_id, cause), n in repeated_sorted:
        title = topics.get(topic_id).title_fa if topic_id in topics else "مبحث نامشخص"
        cause_fa = CAUSE_FA.get(cause, cause)
        alerts.append(
            _alert(
                "repeated_error",
                "warning",
                f"خطای تکراری حل‌نشده — {title}",
                f"{n} خطای {cause_fa} در این مبحث هنوز باز است.",
                "یک جلسه مرور هدفمند روی همین مبحث و سپس بازآزمون ترمیمی تا پایان هفته.",
                topic_id=topic_id,
            )
        )

    # ۵) نمره‌ی زیر آستانه (آستانه‌ها از Settings) + ۶) بهبود اخیر
    if attempts:
        last = attempts[-1]
        pct = last.percent
        if pct is not None:
            last_exam = await db.get(Exam, last.exam_id)
            exam_title = last_exam.title_fa if last_exam else f"آزمون #{last.exam_id}"
            if pct < s.threshold_weak:
                alerts.append(
                    _alert(
                        "low_score",
                        "danger",
                        "نمره‌ی زیر آستانه‌ی لازم",
                        f"آخرین آزمون «{exam_title}» با {pct}٪ ثبت شده و زیر آستانه‌ی {s.threshold_weak}٪ است.",
                        "مباحث پرتکرار همین آزمون مشخص و تمرین هدفمند ۱۰ سؤالی در هفته‌ی جاری انجام شود.",
                    )
                )
            elif pct < s.threshold_consolidating:
                alerts.append(
                    _alert(
                        "low_score",
                        "warning",
                        "نمره‌ی کمتر از سطح تثبیت",
                        f"آخرین آزمون «{exam_title}» با {pct}٪ ثبت شده و پایین‌تر از آستانه‌ی "
                        f"{s.threshold_consolidating}٪ است.",
                        "مرور مباحث نادرست همین آزمون و بازآزمون کوتاه تا پایان هفته پیشنهاد می‌شود.",
                    )
                )
        if len(attempts) >= 2:
            a_now, a_prev = attempts[-1].percent, attempts[-2].percent
            if a_now is not None and a_prev is not None and (a_now - a_prev) >= POSITIVE_DELTA_PCT:
                alerts.append(
                    _alert(
                        "improvement",
                        "info",
                        "بهبود عملکرد در آزمون اخیر",
                        f"درصد آخرین آزمون نسبت به آزمون قبل {round(a_now - a_prev, 1)} واحد بهتر شده است.",
                        "همین روند مرور منظم را ادامه دهید و از تقویت فشار اضافه خودداری کنید.",
                    )
                )

    # ۷) افت ماندگاری (E خوب ولی R افت کرده)
    retention_drops = [
        st
        for st in states
        if st.evidence_count >= s.evidence_min_for_status
        and st.effective_mastery >= s.threshold_consolidating
        and st.retention < 0.5
    ]
    retention_drops.sort(key=lambda st: st.retention)
    for st in retention_drops[:MAX_RETENTION_ALERTS]:
        title = topics.get(st.topic_id).title_fa if st.topic_id in topics else "مبحث نامشخص"
        alerts.append(
            _alert(
                "retention_drop",
                "warning",
                f"افت ماندگاری — {title}",
                f"تسط این مبحث {round(st.effective_mastery, 1)}٪ است ولی ماندگاری به "
                f"{round(st.retention * 100)}٪ رسیده و در حال فراموشی است.",
                "مرور فاصله‌دار ۱۵ دقیقه‌ای در سه روز آینده برای این مبحث کافی است.",
                topic_id=st.topic_id,
            )
        )

    # ۸) مباحث نیازمند توجه (ضعیف/بحرانی) — حداکثر ۳ مورد
    weak = [
        st
        for st in states
        if st.evidence_count >= s.evidence_min_for_status
        and status_of(st.effective_mastery, st.evidence_count) in ("weak", "critical")
    ]
    weak.sort(key=lambda st: st.effective_mastery)
    for st in weak[:MAX_WEAK_TOPIC_ALERTS]:
        title = topics.get(st.topic_id).title_fa if st.topic_id in topics else "مبحث نامشخص"
        sev = "danger" if status_of(st.effective_mastery, st.evidence_count) == "critical" else "warning"
        alerts.append(
            _alert(
                "weak_topic",
                sev,
                f"نیازمند توجه — {title}",
                f"تسط فعلی این مبحث {round(st.effective_mastery, 1)}٪ و زیر آستانه‌ی "
                f"{s.threshold_consolidating}٪ است.",
                "مرور پیش‌نیاز، ۱۰ سؤال هدفمند و سپس یک آزمون کوتاه ۵ سؤالی.",
                topic_id=st.topic_id,
            )
        )

    # ۹) مداخله مؤثر نبوده (بعد از ۲ شاهد جدید، E تغییر معنادار نداشته)
    ineffective: list[tuple[StudentTopicState, float]] = []
    for st in states:
        hist = list(st.history or [])
        if len(hist) < 2:
            continue
        last = hist[-1]
        if status_of(last.get("e", 0.0), last.get("evidence_count", 0)) == "mastered":
            continue
        base = None
        for h in hist[:-1]:
            if (last.get("evidence_count", 0) - h.get("evidence_count", 0)) >= 2:
                base = h
                break
        if base is None:
            continue
        drift = abs(float(last.get("e", 0.0)) - float(base.get("e", 0.0)))
        if drift < INTERVENTION_EPSILON:
            ineffective.append((st, drift))
    ineffective.sort(key=lambda pair: pair[0].effective_mastery)
    for st, _drift in ineffective[:MAX_INTERVENTION_ALERTS]:
        title = topics.get(st.topic_id).title_fa if st.topic_id in topics else "مبحث نامشخص"
        alerts.append(
            _alert(
                "intervention_ineffective",
                "warning",
                f"مداخله‌ی اخیر مؤثر نبود — {title}",
                f"پس از دو شاهد جدید، تسط این مبحث تغییر معناداری نداشته است "
                f"(تسط فعلی {round(st.effective_mastery, 1)}٪).",
                "روش مرور عوض شود: پیش‌نیاز مبحث + تمرین مسئله‌محور به‌جای تکرار مطلب.",
                topic_id=st.topic_id,
            )
        )

    alerts.sort(key=lambda a: SEVERITY_RANK.get(a["severity"], 3))
    alerts = alerts[:MAX_ALERTS]
    return alerts


# ------------------------------------------------------------------ §14 گزارش هفتگی


def week_bounds(today: date) -> tuple[date, date]:
    """بازه‌ی هفته‌ی جاری به تقویم هفتگی شنبه تا جمعه (شنبه = ابتدای هفته)."""
    start = today - timedelta(days=(today.weekday() - 5) % 7)
    return start, start + timedelta(days=6)


async def build_weekly_report(db: AsyncSession, student_id: int) -> tuple[str, dict]:
    """گزارش هفتگی تجمیعی یک فرزند (سند §14) — قطعی، ارزان و بدون مقایسه."""
    s = get_settings()
    now = datetime.utcnow()
    week_start, week_end = week_bounds(date.today())
    window_start = datetime.combine(week_start, time.min)

    pm = await progress_mastery(db, student_id)
    states: list[StudentTopicState] = pm["states"]
    topics: dict[int, Topic] = pm["topics"]
    tasks: list[PlanTask] = pm["tasks"]

    week_tasks = [t for t in tasks if week_start <= t.for_date <= week_end]
    week_done = sum(1 for t in week_tasks if t.status == "done")

    retentions = [st.retention for st in states if st.evidence_count >= s.evidence_min_for_status]
    weak_topics = [
        st
        for st in states
        if st.evidence_count >= s.evidence_min_for_status
        and status_of(st.effective_mastery, st.evidence_count) in ("weak", "critical")
    ]
    weak_topics.sort(key=lambda st: st.effective_mastery)

    attempts = await _graded_attempts(db, student_id)
    week_attempts = [a for a in attempts if _naive_utc(a.submitted_at) and _naive_utc(a.submitted_at) >= window_start]
    exams_ctx, _points, _totals = await _exam_context(db, {a.exam_id for a in week_attempts})
    week_percents = [a.percent for a in week_attempts if a.percent is not None]
    exam_rows = []
    prev_percent = None
    for a in attempts:
        if a not in week_attempts:
            continue
        pct = a.percent
        exam_rows.append(
            {
                "attempt_id": a.id,
                "exam_id": a.exam_id,
                "title": exams_ctx[a.exam_id].title_fa if a.exam_id in exams_ctx else f"آزمون #{a.exam_id}",
                "subject": exams_ctx[a.exam_id].subject if a.exam_id in exams_ctx else None,
                "percent": pct,
                "delta": round(pct - prev_percent, 2) if pct is not None and prev_percent is not None else None,
                "submitted_at": _iso(a.submitted_at),
            }
        )
        if pct is not None:
            prev_percent = pct

    # فعالیت هفته: شواهد یادگیری + زمان پاسخ به سؤال‌ها
    week_evidence = len(
        list(
            (
                await db.execute(
                    select(Evidence.id)
                    .where(Evidence.student_user_id == student_id, Evidence.occurred_at >= window_start)
                )
            ).scalars()
        )
    )
    week_answers = (
        (
            await db.execute(
                select(AttemptAnswer)
                .join(ExamAttempt, ExamAttempt.id == AttemptAnswer.attempt_id)
                .where(
                    ExamAttempt.student_user_id == student_id,
                    ExamAttempt.submitted_at.is_not(None),
                    ExamAttempt.submitted_at >= window_start,
                )
            )
        )
        .scalars()
        .all()
    )
    minutes_spent = round(sum((a.time_spent_ms or 0) for a in week_answers) / 60000.0, 1)

    open_errors = await _open_errors_of(db, student_id)
    all_errors = list(
        (
            await db.execute(select(ErrorRecord).where(ErrorRecord.student_user_id == student_id))
        ).scalars()
    )
    by_cause: dict[str, int] = {}
    for e in open_errors:
        by_cause[e.cause] = by_cause.get(e.cause, 0) + 1
    repeated_open = sum(
        1
        for (_tid, _c), n in _count_pairs(open_errors)
        if n >= REPEAT_ERROR_MIN
    )

    alerts = await build_alerts(db, student_id)
    actions: list[str] = []
    for al in alerts:
        if al["action"] not in actions:
            actions.append(al["action"])
        if len(actions) >= 4:
            break
    if not actions:
        actions = ["مرور کوتاه روزانه روی مباحث نیازمند توجه، هفته‌ای یک بازآزمون کوتاه."]

    counts = {"mastered": 0, "consolidating": 0, "weak": 0, "critical": 0, "unknown": 0}
    for st in states:
        k = status_of(st.effective_mastery, st.evidence_count)
        counts[k] = counts.get(k, 0) + 1

    payload = {
        "student_id": student_id,
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "generated_at": now.isoformat(),
        "plan": {
            "progress_pct": pm["progress_pct"],
            "total": len(tasks),
            "done": sum(1 for t in tasks if t.status == "done"),
            "week_total": len(week_tasks),
            "week_done": week_done,
            "week_done_pct": round(100.0 * week_done / len(week_tasks), 1) if week_tasks else 0.0,
            "overdue": sum(1 for t in tasks if t.for_date < date.today() and t.status in ("pending", "missed")),
        },
        "mastery": {
            "mastery_pct": pm["mastery_pct"],
            "avg_retention": round(sum(retentions) / len(retentions), 2) if retentions else None,
            "status_counts": counts,
            "weak_topics": [
                {
                    "topic_id": st.topic_id,
                    "title": topics.get(st.topic_id).title_fa if st.topic_id in topics else None,
                    "effective_mastery": round(st.effective_mastery, 1),
                    "retention": round(st.retention, 2),
                }
                for st in weak_topics[:5]
            ],
        },
        "exams": {
            "count": len(week_attempts),
            "avg_percent": round(sum(week_percents) / len(week_percents), 1) if week_percents else None,
            "list": exam_rows,
        },
        "activity": {
            "evidence_count": week_evidence,
            "questions_answered": len(week_answers),
            "minutes_spent": minutes_spent,
            "tasks_done": week_done,
        },
        "errors": {
            "total": len(all_errors),
            "open": len(open_errors),
            "repeated_open": repeated_open,
            "by_cause": [
                {"cause": c, "cause_fa": CAUSE_FA.get(c, c), "count": n}
                for c, n in sorted(by_cause.items(), key=lambda kv: (-kv[1], kv[0]))
            ],
        },
        "alerts": alerts,
        "actions": actions,
        "note_fa": NOTE_NO_RANK,
    }
    return week_start.isoformat(), payload


def _count_pairs(rows) -> list[tuple[tuple, int]]:
    """شمارش تکرار (مبحث، علت خطا) برای خطاهای باز."""
    counts: dict[tuple, int] = {}
    for e in rows:
        key = (e.topic_id, e.cause)
        counts[key] = counts.get(key, 0) + 1
    return list(counts.items())


# -------------------------------- §2 وضعیت یادگیری به تفکیک درس -------------------------------

STATUS_FA = {
    "mastered": "مسلط",
    "consolidating": "در حال تثبیت",
    "weak": "ضعیف",
    "critical": "بحرانی",
    "unknown": "نیازمند داده",
}

TREND_FA = {"up": "↑ بهبود", "down": "↓ افت", "flat": "→ بدون تغییر", "none": "—"}


async def _subject_of_topics(db: AsyncSession) -> dict[int, str]:
    """مبحث ← درس: Topic ← Chapter ← Book.subject (یک کوئری، بدون N+1)."""
    rows = (
        await db.execute(
            select(Topic.id, Chapter.book_id)
            .join(Chapter, Chapter.id == Topic.chapter_id)
        )
    ).all()
    if not rows:
        return {}
    book_ids = {book_id for _tid, book_id in rows}
    books = {
        b.id: b.subject
        for b in (
            (await db.execute(select(Book).where(Book.id.in_(book_ids)))).scalars()
            if book_ids
            else []
        )
    }
    return {topic_id: books.get(book_id) for topic_id, book_id in rows}


def _history_trend(history: list | None) -> tuple[str, float | None]:
    """روند از روی history خودِ SLM (بدون ساخت عدد بیرونی): دو مقدار آخرِ tسط."""
    if not history or len(history) < 2:
        return "none", None
    entries = sorted(history, key=lambda h: str(h.get("at") or ""))
    prev = entries[-2].get("m")
    last = entries[-1].get("m")
    if prev is None or last is None:
        return "none", None
    delta = round(float(last) - float(prev), 1)
    if delta > 0.5:
        return "up", delta
    if delta < -0.5:
        return "down", delta
    return "flat", delta


async def subject_status(db: AsyncSession, student_id: int) -> dict:
    """سند §2: وضعیت هر درس با روند + مباحث نیازمند توجه/تثبیت‌شده +
    تاریخ آخرین ارزیابی + نقاط قوت — تا سطح مبحث قابل پیمایش است."""
    s = get_settings()
    states = await _states_of(db, student_id)
    topics = await _topics_map(db)
    subject_of = await _subject_of_topics(db)

    # آخرین ارزیابی هر مبحث از history (خودِ داده‌ی SLM)
    last_eval: dict[int, datetime] = {}
    for st in states:
        for h in st.history or []:
            at = _naive_utc(datetime.fromisoformat(h["at"]) if isinstance(h.get("at"), str) else h.get("at"))
            if at and (st.topic_id not in last_eval or at > last_eval[st.topic_id]):
                last_eval[st.topic_id] = at

    errors = await _open_errors_of(db, student_id)
    cause_by_topic: dict[int, dict[str, int]] = {}
    for e in errors:
        cause_by_topic.setdefault(e.topic_id, {})[e.cause] = (
            cause_by_topic.get(e.topic_id, {}).get(e.cause, 0) + 1
        )

    by_subject: dict[str, list[StudentTopicState]] = {}
    for st in states:
        subj = subject_of.get(st.topic_id) or "other"
        by_subject.setdefault(subj, []).append(st)

    subjects = []
    for subj, rows in sorted(by_subject.items()):
        with_data = [r for r in rows if r.evidence_count >= s.evidence_min_for_status]
        suppressed = False  # نمای والد همیشه روی یک فرزند است؛ قاعده حداقل جمعیت اینجا معنا ندارد
        mastery = (
            round(sum(r.effective_mastery for r in with_data) / len(with_data), 1)
            if with_data
            else None
        )
        statuses = [status_of(r.effective_mastery, r.evidence_count) for r in rows]
        attention = [r for r in rows if status_of(r.effective_mastery, r.evidence_count) in ("weak", "critical")]
        consolidated = [r for r in rows if status_of(r.effective_mastery, r.evidence_count) == "mastered"]

        # روند درس: میانگین Δ دو مقدار آخرِ history مباحث آن درس
        deltas = [d for r in rows for d in [_history_trend(r.history)[1]] if d is not None]
        if deltas:
            avg_delta = round(sum(deltas) / len(deltas), 1)
            trend = "up" if avg_delta > 0.5 else "down" if avg_delta < -0.5 else "flat"
        else:
            avg_delta, trend = None, "none"

        # خطای غالب و افت اخیر
        causes: dict[str, int] = {}
        recent_drop = None
        for r in rows:
            for c, n in cause_by_topic.get(r.topic_id, {}).items():
                causes[c] = causes.get(c, 0) + n
            tr, dl = _history_trend(r.history)
            if tr == "down" and dl is not None:
                recent_drop = r.topic_id
        dominant = max(causes, key=causes.get) if causes else None

        subject_rows = sorted(
            rows,
            key=lambda r: (status_of(r.effective_mastery, r.evidence_count) != "weak"
                           and status_of(r.effective_mastery, r.evidence_count) != "critical",
                           r.effective_mastery),
        )
        topic_rows = []
        for r in subject_rows:
            t = topics.get(r.topic_id)
            if t is None:
                continue
            st_key = status_of(r.effective_mastery, r.evidence_count)
            tr, dl = _history_trend(r.history)
            causes_for_topic = cause_by_topic.get(r.topic_id, {})
            weak_causes = sorted(causes_for_topic, key=causes_for_topic.get, reverse=True)
            similar = sum(causes_for_topic.values())
            topic_rows.append(
                {
                    "topic_id": r.topic_id,
                    "title": t.title_fa,
                    "mastery": round(r.effective_mastery, 1),
                    "status": st_key,
                    "status_fa": STATUS_FA[st_key],
                    "needs_attention": st_key in ("weak", "critical"),
                    "trend": tr,
                    "trend_delta": dl,
                    "trend_fa": TREND_FA[tr],
                    "dominant_error": weak_causes[0] if weak_causes else None,
                    "dominant_error_fa": CAUSE_FA.get(weak_causes[0], weak_causes[0]) if weak_causes else None,
                    "similar_errors": similar,
                    "last_evidence_at": _iso(last_eval.get(r.topic_id)),
                    "suggestion_fa": (
                        "مرور پیش‌نیاز + آزمون کوتاه"
                        if st_key in ("weak", "critical")
                        else "تمرین هدفمند برای تثبیت"
                        if st_key == "consolidating"
                        else "مرور فاصله‌دار برای ماندگاری"
                    ),
                }
            )

        subjects.append(
            {
                "subject": None if subj == "other" else subj,
                "current_mastery": mastery,
                "status": (
                    "unknown"
                    if mastery is None
                    else "mastered"
                    if mastery >= s.threshold_mastered
                    else "consolidating"
                    if mastery >= s.threshold_consolidating
                    else "weak"
                ),
                "status_fa": (
                    "نیازمند داده"
                    if mastery is None
                    else "مسلط"
                    if mastery >= s.threshold_mastered
                    else "در حال تثبیت"
                    if mastery >= s.threshold_consolidating
                    else "ضعیف"
                ),
                "trend": trend,
                "trend_delta": avg_delta,
                "trend_fa": TREND_FA[trend],
                "topics_count": len(rows),
                "attention_count": len(attention),
                "consolidated_count": len(consolidated),
                "dominant_error_fa": CAUSE_FA.get(dominant, dominant) if dominant else None,
                "recent_drop_topic_id": recent_drop,
                "last_assessed_at": _iso(max(last_eval.values())) if last_eval else None,
                "suppressed": suppressed,
                "topics": topic_rows,
            }
        )
    # مرتب‌سازی: درس‌های نیازمند توجه اول (نمایش قابل اقدام برای والد)
    subjects.sort(key=lambda r: (-r["attention_count"], r["current_mastery"] if r["current_mastery"] is not None else -1))

    strengths = [
        {"subject": r["subject"], "current_mastery": r["current_mastery"]}
        for r in subjects
        if r["current_mastery"] is not None and r["current_mastery"] >= s.threshold_mastered
    ]
    attention_subjects = [
        {"subject": r["subject"], "attention_count": r["attention_count"]}
        for r in subjects
        if r["attention_count"]
    ]

    return {
        "student_id": student_id,
        "subjects": subjects,
        "strengths": strengths,
        "attention_subjects": attention_subjects,
        "thresholds": {
            "mastered": s.threshold_mastered,
            "consolidating": s.threshold_consolidating,
            "weak": s.threshold_weak,
        },
        "note_fa": (
            "هر درس با روند، تعداد مباحث نیازمند توجه/تثبیت‌شده و تاریخ آخرین ارزیابی نمایش "
            "داده می‌شود؛ درصدهای خام بدون روند معنا ندارند (سند والدین §2)."
        ),
    }


# -------------------------------- §4 سه نوع مقایسه -------------------------------


async def comparisons(db: AsyncSession, student_id: int, class_allowed: bool = True) -> dict:
    """سند §4: سه مقایسه — «نسبت به خودش»، «نسبت به هدف دوره» و «نسبت به کالس»
    (آخری فقط در صورت مجاز بودنِ مجوزِ پیوند و رعایت حداقل جمعیت کالس)."""
    s = get_settings()
    states = await _states_of(db, student_id)
    subject_of = await _subject_of_topics(db)

    profile = (
        await db.execute(select(StudentProfile).where(StudentProfile.user_id == student_id))
    ).scalar_one_or_none()

    by_subject: dict[str, list[StudentTopicState]] = {}
    for st in states:
        by_subject.setdefault(subject_of.get(st.topic_id) or "other", []).append(st)

    # میانگین کالس (هم‌کلاسی‌ها، بدون خودِ فرزند) — سرکوب زیر حداقل جمعیت
    class_avg: dict[str, float | None] = {}
    class_sizes: dict[str, int] = {}
    if profile is not None and profile.class_id is not None:
        peer_ids = [
            p.user_id
            for p in (
                (
                    await db.execute(
                        select(StudentProfile).where(StudentProfile.class_id == profile.class_id)
                    )
                ).scalars()
            )
            if p.user_id != student_id
        ]
        peers = list(
            (
                await db.execute(
                    select(StudentTopicState).where(StudentTopicState.student_user_id.in_(peer_ids))
                )
            ).scalars()
            if peer_ids
            else []
        )
        by_subj_peers: dict[str, list[StudentTopicState]] = {}
        for st in peers:
            by_subj_peers.setdefault(subject_of.get(st.topic_id) or "other", []).append(st)
        for subj in by_subject:
            rows = [
                r
                for r in by_subj_peers.get(subj, [])
                if r.evidence_count >= s.evidence_min_for_status
            ]
            class_sizes[subj] = len({r.student_user_id for r in rows})
            if class_allowed and class_sizes[subj] >= s.min_group_size:
                class_avg[subj] = round(sum(r.effective_mastery for r in rows) / len(rows), 1)
            else:
                class_avg[subj] = None

    goal = PERIOD_GOAL_MASTERY
    rows = []
    for subj, subj_states in sorted(by_subject.items()):
        with_data = [r for r in subj_states if r.evidence_count >= s.evidence_min_for_status]
        current = (
            round(sum(r.effective_mastery for r in with_data) / len(with_data), 1)
            if with_data
            else None
        )
        # نسبت به خودش: میانگین Δ دو مقدار آخر history
        deltas = [d for r in subj_states for d in [_history_trend(r.history)[1]] if d is not None]
        self_delta = round(sum(deltas) / len(deltas), 1) if deltas else None
        previous = None if current is None or self_delta is None else round(current - self_delta, 1)

        avg = class_avg.get(subj)
        rows.append(
            {
                "subject": None if subj == "other" else subj,
                "self": {
                    "previous": previous,
                    "current": current,
                    "delta": self_delta,
                    "note_fa": "مقایسه با وضعیت خودِ فرزند در دوره/ارزیابی قبلی.",
                },
                "period_goal": {
                    "goal": goal,
                    "current": current,
                    "gap": None if current is None else round(current - goal, 1),
                    "note_fa": "هدف دوره یک عدد برنامه‌ریزی‌شده است، نه نمره‌ی دیگران.",
                },
                "class": {
                    "allowed": class_allowed,
                    "class_avg": avg,
                    "student": current,
                    "gap": None if avg is None or current is None else round(current - avg, 1),
                    "suppressed": avg is None,
                    "reason_fa": (
                        None
                        if avg is not None
                        else (
                            "نمایش میانگین کالس برای این درس مجاز نیست (مجوزِ پیوند والد–فرزند)."
                            if not class_allowed
                            else f"زیر حداقل جمعیت {s.min_group_size} نفر؛ میانگین کالس نمایش داده نمی‌شود."
                        )
                    ),
                },
            }
        )

    return {
        "student_id": student_id,
        "min_group": s.min_group_size,
        "class_comparison_allowed": class_allowed,
        "comparisons": rows,
        "note_fa": (
            "سه نوع مقایسه وجود دارد و رتبه تنها معیار موفقیت نیست؛ مقایسه با کالس فقط در "
            "صورت مجاز بودن مجوزِ همین پیوند والد–فرزند و رعایت حداقل جمعیت نمایش داده می‌شود "
            "(سند والدین §4 و §17)."
        ),
    }


# ------------------------------- §9 حضور و جلسات --------------------------------


async def attendance_and_sessions(db: AsyncSession, student_id: int) -> dict:
    """سند §9: حضور مدرسه + جلسات گذشته/آینده (خصوصی/مدرسه/جلسه با والد) با
    موضوع، گزارش، تکلیف و وضعیت انجام آن."""
    today = date.today()
    attendance = list(
        (
            await db.execute(
                select(SchoolAttendance)
                .where(SchoolAttendance.student_user_id == student_id)
                .order_by(SchoolAttendance.on_date.desc())
                .limit(60)
            )
        ).scalars()
    )
    counts: dict[str, int] = {}
    for a in attendance:
        counts[a.status] = counts.get(a.status, 0) + 1
    present_like = counts.get("present", 0) + counts.get("late", 0) + counts.get("excused", 0)
    attendance_rate = (
        round(100.0 * present_like / len(attendance), 1) if attendance else None
    )

    meetings = list(
        (
            await db.execute(
                select(ParentMeeting)
                .where(ParentMeeting.student_user_id == student_id)
                .order_by(ParentMeeting.scheduled_at.desc())
            )
        ).scalars()
    )
    tutor_ids = {m.tutor_user_id for m in meetings if m.tutor_user_id}
    tutors = {
        u.id: u.full_name
        for u in (
            ((await db.execute(select(User).where(User.id.in_(tutor_ids)))).scalars()
             if tutor_ids else [])
        )
    }

    KIND_FA = {
        "private_session": "جلسه معلم خصوصی",
        "school_session": "جلسه مدرسه",
        "parent_meeting": "جلسه والدین و معلم",
    }
    STATUS_FA_M = {
        "scheduled": "برنامه‌ریزی‌شده",
        "held": "برگزارشده",
        "missed": "ازدست‌رفته",
        "cancelled": "لغوشده",
    }
    TASK_FA = {"pending": "در انتظار", "done": "انجام شده", "skipped": "انجام نشد"}

    def _m_row(m: ParentMeeting) -> dict:
        return {
            "id": m.id,
            "kind": m.kind,
            "kind_fa": KIND_FA.get(m.kind, m.kind),
            "subject": m.subject,
            "topic_fa": m.topic_fa,
            "tutor_user_id": m.tutor_user_id,
            "tutor_name": tutors.get(m.tutor_user_id),
            "scheduled_at": _iso(m.scheduled_at),
            "duration_min": m.duration_min,
            "status": m.status,
            "status_fa": STATUS_FA_M.get(m.status, m.status),
            "report_fa": m.report_fa,
            "task_fa": m.task_fa,
            "task_status": m.task_status,
            "task_status_fa": TASK_FA.get(m.task_status, m.task_status),
            "is_past": _naive_utc(m.scheduled_at) is not None
            and _naive_utc(m.scheduled_at) < datetime.utcnow(),
        }

    now = datetime.utcnow()
    past = [m for m in meetings if (_naive_utc(m.scheduled_at) or now) <= now]
    upcoming = [m for m in meetings if (_naive_utc(m.scheduled_at) or now) > now]
    missed = [m for m in meetings if m.status == "missed"]
    pending_tasks = [m for m in meetings if m.task_fa and m.task_status in (None, "pending")]

    return {
        "student_id": student_id,
        "attendance": {
            "days": len(attendance),
            "rate_pct": attendance_rate,
            "counts": counts,
            "absent": counts.get("absent", 0),
            "late": counts.get("late", 0),
            "excused": counts.get("excused", 0),
            "rows": [
                {
                    "on_date": a.on_date.isoformat(),
                    "status": a.status,
                    "status_fa": {
                        "present": "حاضر",
                        "absent": "غایب",
                        "late": "تاخیر",
                        "excused": "غیبت موجه",
                    }.get(a.status, a.status),
                    "note": a.note,
                }
                for a in attendance
            ],
        },
        "sessions": {
            "total": len(meetings),
            "upcoming": [_m_row(m) for m in upcoming],
            "past": [_m_row(m) for m in past],
            "missed": [_m_row(m) for m in missed],
            "pending_tasks": [_m_row(m) for m in pending_tasks],
        },
        "note_fa": (
            "حضور و جلسات فقط برای همین فرزند نمایش داده می‌شود؛ گزارش جلسه و تکلیف آن از "
            "همان جریان معلم خصوصی می‌آید (سند والدین §9)."
        ),
    }


# ----------------------------- §15 دستیار هوشمند والد ----------------------------

ASSISTANT_MAX_Q = 400

_INTENTS = (
    ("drop", ("افت", "پایین", "ضعیف", "مشکل", "چرا")),
    ("best", ("مهم‌ترین", "بزرگ‌ترین", "الان", "اولویت")),
    ("effective", ("مؤثر", "مفيد", "مفید", "تاثیر", "اثر", "انجام داده")),
    ("progress", ("پیشرفت", "بهبود", "بهتر شد", "پیشرفت‌ای")),
    ("meeting", ("جلسه", "معلم", "مطرح", "بپرسم")),
)


def _detect_intent(q: str) -> str:
    for key, words in _INTENTS:
        if any(w in q for w in words):
            return key
    return "general"


async def assistant_answer(db: AsyncSession, student_id: int, question: str) -> dict:
    """سند §15: پاسخ فقط بر پایه‌ی داده‌ی واقعیِ همان فرزند (مباحث، خطاها،
    آزمون‌ها، فعالیت و مداخله‌ها) — قاعده‌محور و بدون مدل بیرونی؛ هرگز قضاوت
    شخصیتی/روان‌شناختی نمی‌کند و هیچ داده‌ای از دیگران را فاش نمی‌کند."""
    q = (question or "").strip()
    if not q:
        raise ValueError("پرسش خالی است")
    if len(q) > ASSISTANT_MAX_Q:
        raise ValueError("پرسش بیش از حد طولانی است")

    s = get_settings()
    pm = await progress_mastery(db, student_id)
    states: list[StudentTopicState] = pm["states"]
    topics: dict[int, Topic] = pm["topics"]
    subject_of = await _subject_of_topics(db)
    errors = await _open_errors_of(db, student_id)
    attempts = await _graded_attempts(db, student_id)

    # مباحث ضعیف/بحرانی با علت غالب
    weak_rows = []
    for st in states:
        k = status_of(st.effective_mastery, st.evidence_count)
        if k not in ("weak", "critical"):
            continue
        causes: dict[str, int] = {}
        for e in errors:
            if e.topic_id == st.topic_id:
                causes[e.cause] = causes.get(e.cause, 0) + 1
        dominant = max(causes, key=causes.get) if causes else None
        weak_rows.append(
            {
                "topic_id": st.topic_id,
                "title": topics[st.topic_id].title_fa if st.topic_id in topics else f"#{st.topic_id}",
                "subject": subject_of.get(st.topic_id),
                "mastery": round(st.effective_mastery, 1),
                "status": k,
                "dominant_error_fa": CAUSE_FA.get(dominant, dominant) if dominant else None,
                "error_count": sum(causes.values()),
            }
        )
    weak_rows.sort(key=lambda r: r["mastery"])

    strong_rows = sorted(
        [
            {
                "topic_id": st.topic_id,
                "title": topics[st.topic_id].title_fa if st.topic_id in topics else f"#{st.topic_id}",
                "subject": subject_of.get(st.topic_id),
                "mastery": round(st.effective_mastery, 1),
            }
            for st in states
            if status_of(st.effective_mastery, st.evidence_count) == "mastered"
        ],
        key=lambda r: -r["mastery"],
    )

    # پیشرفت از روی history (دو مقدار آخر) — همان داده‌ی SLM
    improved, declined = [], []
    for st in states:
        tr, dl = _history_trend(st.history)
        if tr == "up" and dl is not None:
            improved.append((dl, st.topic_id))
        elif tr == "down" and dl is not None:
            declined.append((dl, st.topic_id))
    improved.sort(reverse=True)
    declined.sort(reverse=True)

    percents = [float(a.percent) for a in attempts if a.percent is not None]
    exam_avg = round(sum(percents) / len(percents), 1) if percents else None
    exam_delta = round(percents[-1] - percents[-2], 1) if len(percents) >= 2 else None

    intent = _detect_intent(q)
    subject_hint = None
    for subj, fa in SUBJECT_HINTS.items():
        if fa in q or subj in q:
            subject_hint = subj
            break

    def _subj(rows: list[dict]) -> list[dict]:
        return [r for r in rows if subject_hint is None or r.get("subject") == subject_hint]

    lines: list[str] = []
    if intent == "drop":
        rows = _subj(weak_rows)
        if rows:
            top = rows[0]
            lines.append(
                f"در «{top['title']}» تسط فعلی {fa_num(top['mastery'])}٪ و وضعیت "
                f"{STATUS_FA[top['status']]} است."
            )
            if top["dominant_error_fa"]:
                lines.append(
                    f"خطای غالب ثبت‌شده {top['dominant_error_fa']} است ({fa_num(top['error_count'])} مورد باز)."
                )
            lines.append("پیشنهاد: ۲۰ دقیقه مرور پیش‌نیاز، سپس ۵ سؤال هدفمند و آزمون کوتاه.")
        else:
            lines.append("برای این درس مبحثی با وضعیت ضعیف/بحرانی ثبت نشده است.")
        if exam_delta is not None and exam_delta < 0:
            lines.append(
                f"میانگین درصد آزمون‌های اخیر {fa_num(exam_avg)}٪ است و نسبت به آزمون قبلی "
                f"{fa_num(exam_delta)} واحد تغییر داشته است."
            )
    elif intent == "best":
        rows = _subj(weak_rows) or weak_rows
        if rows:
            top = rows[0]
            lines.append(
                f"مهم‌ترین مبحث نیازمند توجه «{top['title']}» است "
                f"(تسط {fa_num(top['mastery'])}٪"
                + (f"، خطای غالب {top['dominant_error_fa']}" if top["dominant_error_fa"] else "")
                + ")."
            )
            lines.append("اقدام: مرور پیش‌نیاز + آزمون کوتاه در همین هفته.")
        else:
            lines.append("مبحث نیازمند توجهی ثبت نشده است.")
    elif intent == "effective":
        tasks = pm["tasks"]
        done = sum(1 for t in tasks if t.status == "done")
        lines.append(
            f"{fa_num(done)} از {fa_num(len(tasks))} کارِ برنامه انجام شده است "
            f"(پیشرفت {fa_num(pm['progress_pct'])}٪)."
        )
        if improved:
            title = topics[improved[0][1]].title_fa if improved[0][1] in topics else ""
            lines.append(f"بهبود مشاهده‌شده: «{title}» با {fa_num(improved[0][0])} واحد رشد تسط.")
        else:
            lines.append("در داده‌های اخیر بهبود معناداری ثبت نشده است.")
        if weak_rows:
            lines.append(
                f"اما {fa_num(len(weak_rows))} مبحث همچنان زیر آستانه تثبیت است؛ اولویت با همان‌هاست."
            )
    elif intent == "progress":
        if improved:
            lines.append(
                "دروس/مباحث دارای پیشرفت: "
                + "، ".join(
                    f"{topics[t].title_fa if t in topics else '#' + str(t)} (+{fa_num(d)} واحد)"
                    for d, t in improved[:5]
                )
                + "."
            )
        else:
            lines.append("در دو ماه اخیر بهبود معناداری در تسط مباحث ثبت نشده است.")
        if declined:
            lines.append(
                "مباحثی که افت داشته‌اند: "
                + "، ".join(
                    f"{topics[t].title_fa if t in topics else '#' + str(t)} ({fa_num(d)} واحد)"
                    for d, t in declined[:3]
                )
                + "."
            )
    elif intent == "meeting":
        lines.append("موضوعات پیشنهادی برای جلسه با معلم:")
        for r in (_subj(weak_rows) or weak_rows)[:3]:
            lines.append(f"- «{r['title']}»: تسط {fa_num(r['mastery'])}٪" + (f"؛ خطای غالب {r['dominant_error_fa']}" if r["dominant_error_fa"] else ""))
        if not weak_rows:
            lines.append("- وضعیت مباحث عمومی است؛ درباره‌ی سرعت پیشروی برنامه بپرسید.")
    else:
        lines.append(
            f"تسط کلی {fa_num(pm['mastery_pct'])}٪ و پیشرفت برنامه {fa_num(pm['progress_pct'])}٪ است."
        )
        if weak_rows:
            lines.append(
                f"{fa_num(len(weak_rows))} مبحث نیازمند توجه است که مهم‌ترین آن «{weak_rows[0]['title']}» است."
            )
        if strong_rows:
            lines.append("نقاط قوت: " + "، ".join(r["title"] for r in strong_rows[:3]) + ".")
        lines.append("برای جزئیات بیشتر بخش «وضعیت یادگیری» را ببینید.")

    answer = " ".join(lines)
    return {
        "student_id": student_id,
        "question": q,
        "answer": answer,
        "answer_fa": answer,
        "intent": intent,
        "subject": subject_hint,
        "references": {
            "weak_topics": (_subj(weak_rows) or weak_rows)[:3],
            "strong_topics": strong_rows[:3],
            "exam_avg": exam_avg,
            "exam_delta": exam_delta,
            "progress_pct": pm["progress_pct"],
            "mastery_pct": pm["mastery_pct"],
        },
        "note_fa": (
            "پاسخ فقط از داده‌های واقعی همین فرزند ساخته شده است؛ دستیار درباره‌ی شخصیت یا "
            "هوش او قضاوت نمی‌کند و به داده‌ی دانش‌آموزان دیگر دسترسی ندارد (سند والدین §15)."
        ),
    }


SUBJECT_HINTS = {
    "math": "ریاضی",
    "physics": "فیزیک",
    "chemistry": "شیمی",
    "biology": "زیست",
    "arabic": "عربی",
    "english": "انگلیسی",
    "farsi": "ادبیات",
}


def fa_num(value) -> str:
    """عدد فارسی‌شده برای متن‌های کاربرپسند."""
    if value is None:
        return "—"
    if isinstance(value, float) and value == int(value):
        value = int(value)
    text = str(value)
    table = str.maketrans("0123456789.", "۰۱۲۳۴۵۶۷۸۹٫")
    return text.translate(table)
