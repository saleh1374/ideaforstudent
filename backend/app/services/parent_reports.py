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
from app.models.catalog import Topic
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
