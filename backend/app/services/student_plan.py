"""برنامه دوره‌ای/تقویم دانش‌آموز (student spec §4 «تقویم آموزشی و چرخه
دوهفته‌ای» + §13 «دورهٔ جاری: تقویم دوره، مباحث، روز آزمون، وضعیت ترمیم»)
و تاریخچهٔ تحلیلی آزمون (§7 «نظام ارزیابی» + §13 «آزمون‌ها / تحلیل و کارنامه»).

همه‌چیز از داده‌های موجود محاسبه می‌شود (Period/Topic/PlanTask/Exam/Attempt/
ErrorRecord/Evidence) — جدول جدیدی لازم نیست. همه برچسب‌ها فارسی‌اند و
آستانه‌ها از Settings می‌آیند؛ ثابت‌های نمایشیِ محلی همین ماژول‌اند."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.models.assessment import AttemptAnswer, Exam, ExamAttempt, ExamItem
from app.models.catalog import Book, Chapter, Period, Topic
from app.models.org import StudentProfile
from app.models.plan_control import PlanPause
from app.models.slm import ErrorRecord, Evidence, PlanTask, StudentTopicState
from app.services.slm import (
    EvidenceRecord,
    effective_mastery,
    mastery,
    next_stability,
    retention,
    status_of,
)

sa_sum = func.sum  # میانبر: select(sa_sum(XpEvent.xp)) ⇒ جمع امتیازها

# ------------------------- ثابت‌های محلی (برچسب/بازه نمایشی) -------------------------

KIND_FA = {
    "task": "کار برنامه",
    "exam": "آزمون",
    "period": "دوره آموزشی",
    "retest": "بازآزمون ترمیمی",
    "mission": "مأموریت روزانه",
}

TASK_TYPE_FA = {
    "lesson": "درس",
    "practice": "تمرین",
    "remedial_pack": "بسته ترمیمی",
    "spaced_review": "مرور فاصله‌دار",
    "retest": "بازآزمون",
    "quiz": "آزمونک",
    "cumulative_prep": "آمادگی آزمون تجمعی",
}

EXAM_TYPE_FA = {
    "period_exam": "آزمون دوره‌ای",
    "cumulative": "آزمون تجمعی",
    "quiz": "کوییز",
    "diagnostic": "آزمون تشخیصی",
    "remedial_retest": "بازآزمون ترمیمی",
    "practice": "تمرین",
}

TASK_STATUS_FA = {
    "pending": "در صف",
    "done": "انجام‌شده",
    "missed": "جا‌مانده",
    "moved": "جابه‌جا شده",
}

ERROR_STATUS_FA = {
    "open": "باز",
    "in_remediation": "در حال ترمیم",
    "resolved": "رفع‌شده",
    "relapsed": "بازگشته",
}

# شنبه=۵ … جمعه=۴ در time.weekday()
WEEKDAY_FA = [
    "دوشنبه",
    "سه‌شنبه",
    "چهارشنبه",
    "پنجشنبه",
    "جمعه",
    "شنبه",
    "یکشنبه",
]
# هفتهٔ آموزشی ایران (§4.2): پنجشنبه و جمعه روز آزادند
FREE_WEEKDAYS = {3, 4}

CALENDAR_DEFAULT_DAYS = 7      # نمای پیش‌فرض: ۷ روز
CALENDAR_MAX_DAYS = 62         # سقف بازهٔ درخواستی
SOON_HOURS = 48                # «نزدیک»: سررسید تا ۴۸ ساعت آینده (خواستهٔ محصول)
MISSION_MAX_TASKS = 5          # حداکثر کارِ فهرست مأموریت روزانه
OVERDUE_LOOKBACK_DAYS = 30     # کارهای جا‌ماندهٔ حداکثر ۳۰ روز اخیر در تقویم

_PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa_num(n) -> str:
    """ارقام فارسی داخل متن‌های آمادهٔ نمایش."""
    return str(n).translate(_PERSIAN_DIGITS)


def _naive(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def is_free_day(d: date) -> bool:
    """روز آزاد (پنجشنبه/جمعه) در مقابل روز مدرسه (§4.2)."""
    return d.weekday() in FREE_WEEKDAYS


async def _profile(db: AsyncSession, student_user_id: int) -> StudentProfile | None:
    return (
        await db.execute(select(StudentProfile).where(StudentProfile.user_id == student_user_id))
    ).scalar_one_or_none()


# ---------------------------------------------------------------------------- calendar
async def _student_task_map(db: AsyncSession, student_user_id: int, end: date) -> dict[date, list[PlanTask]]:
    """کارهای برنامه تا پایان بازه + کارهای جا‌ماندهٔ اخیر (برای نمایش عقب‌افتاده)."""
    floor = end - timedelta(days=OVERDUE_LOOKBACK_DAYS)
    rows = (
        await db.execute(
            select(PlanTask)
            .where(
                PlanTask.student_user_id == student_user_id,
                PlanTask.for_date <= end,
                PlanTask.for_date >= floor,
            )
            .order_by(PlanTask.priority.desc(), PlanTask.for_date)
        )
    ).scalars().all()
    by_date: dict[date, list[PlanTask]] = {}
    for t in rows:
        by_date.setdefault(t.for_date, []).append(t)
    return by_date


async def _visible_exams(
    db: AsyncSession, student_user_id: int, task_map: dict[date, list[PlanTask]]
) -> tuple[list[Exam], set[int], set[int]]:
    """آزمون‌های قابل‌نمایشِ این دانش‌آموز + (آزمون‌های دارای تلاش، آزمون‌های ارجاع‌شده).

    آزمون‌های «scope=student» (بازآزمون ترمیمی هدف‌مند) فقط وقتی برای همین
    دانش‌آموز ساخته شده‌اند نمایش داده می‌شوند: یا تلاشی روی آن دارد یا کار
    برنامه‌ای به آن ارجاع داده — تا نمره/عنوان دانش‌آموز دیگری لو نرود."""
    exams = (
        (
            await db.execute(
                select(Exam)
                .options(selectinload(Exam.exam_items))
                .where(Exam.status == "published", Exam.opens_at.is_not(None))
            )
        )
        .scalars()
        .all()
    )
    attempted = {
        eid
        for (eid,) in (
            await db.execute(
                select(ExamAttempt.exam_id).where(ExamAttempt.student_user_id == student_user_id)
            )
        ).all()
    }
    referenced = {
        int(t.payload.get("exam_id"))
        for tasks in task_map.values()
        for t in tasks
        if isinstance(t.payload, dict) and str(t.payload.get("exam_id", "")).isdigit()
    }
    visible = []
    for e in exams:
        if e.scope == "student" and e.id not in attempted and e.id not in referenced:
            continue
        visible.append(e)
    return visible, attempted, referenced


def _exam_item(e: Exam, d: date, *, now: datetime, today: date, attempted: bool) -> dict:
    opens = _naive(e.opens_at)
    closes = _naive(e.closes_at)
    kind = "retest" if e.exam_type == "remedial_retest" else "exam"
    detail_parts = [EXAM_TYPE_FA.get(e.exam_type, e.exam_type), f"{len(e.exam_items)} سؤال"]
    if d == (opens.date() if opens else None):
        detail_parts.append("باز شدن امروز")
    if closes:
        detail_parts.append(f"مهلت تا {closes.strftime('%Y-%m-%d %H:%M')}")
        if closes.date() == d:
            detail_parts.append("آخرین مهلت امروز")
    detail_parts.append("پاسخ داده‌اید ✓" if attempted else "هنوز پاسخ نداده‌اید")

    hl = None
    if not attempted and closes:
        left = closes - now
        if left < timedelta(0):
            hl = "overdue"
        elif left <= timedelta(hours=SOON_HOURS):
            hl = "soon"
        elif opens and opens.date() == today:
            hl = "today"
    elif hl is None and ((opens and opens.date() == today) or (closes and closes.date() == today)):
        hl = "today"

    return {
        "kind": kind,
        "title": e.title_fa,
        "detail": " · ".join(detail_parts),
        "due": (closes or opens).isoformat(sep=" ", timespec="minutes") if (closes or opens) else d.isoformat(),
        "status": "done" if attempted else ("open" if opens and opens <= now else "upcoming"),
        "highlight": hl,
        "ref": {"type": "exam", "id": e.id},
    }


async def _period_topics(db: AsyncSession, period_ids: set[int], grade: str | None) -> dict[int, list[str]]:
    if not period_ids:
        return {}
    by_period: dict[int, list[str]] = {pid: [] for pid in period_ids}
    rows = (
        await db.execute(
            select(Topic.period_id, Topic.title_fa, Book.grade)
            .join(Chapter, Chapter.id == Topic.chapter_id)
            .join(Book, Book.id == Chapter.book_id)
            .where(Topic.period_id.in_(period_ids))
        )
    ).all()
    for pid, title, book_grade in rows:
        # فقط کتاب‌های پایهٔ خود دانش‌آموز (همان‌طور که /books رفتار می‌کند)
        if grade and book_grade != grade:
            continue
        by_period[pid].append(title)
    return by_period


async def _retest_cycle(
    db: AsyncSession, student_user_id: int, *, start: date, end: date, today: date,
    visible: list[Exam], attempted: set[int], referenced: set[int],
) -> tuple[dict[date, list[dict]], dict]:
    """چرخهٔ ترمیم/بازآزمون (فاز ۴): خطای باز ⇒ ساخت بازآزمون؛ بازآزمون ساخته‌شده ⇒ مهلت."""
    errors = (
        await db.execute(
            select(ErrorRecord).where(
                ErrorRecord.student_user_id == student_user_id,
                ErrorRecord.status.in_(["open", "in_remediation", "relapsed"]),
            )
        )
    ).scalars().all()
    topics = {e.topic_id for e in errors}
    if topics:
        titles = {
            t.id: t.title_fa
            for t in (await db.execute(select(Topic).where(Topic.id.in_(topics)))).scalars()
        }
    else:
        titles = {}

    retest_exams = [
        e
        for e in visible
        if e.exam_type == "remedial_retest" and e.id in (attempted | referenced) and _naive(e.closes_at)
    ]
    by_date: dict[date, list[dict]] = {}
    first_open = max(today, start)
    for d in (date.fromordinal(x) for x in range(first_open.toordinal(), end.toordinal() + 1)):
        if not errors:
            break
        live = [
            e
            for e in retest_exams
            if _naive(e.opens_at).date() <= d <= _naive(e.closes_at).date() and e.id not in attempted
        ]
        if live:
            # خودِ آزمونِ ساخته‌شده همان روز در تقویم می‌آید (kind=retest)؛
            # اینجا فقط «هنوز ساخته نشده» را گزارش می‌کنیم تا آیتم تکراری نشود.
            continue
        sample = sorted({titles.get(t, f"مبحث {t}") for t in topics})[:3]
        item = {
            "kind": "retest",
            "title": "چرخه ترمیم و بازآزمون",
            "detail": f"{fa_num(len(errors))} خطا در {fa_num(len(topics))} مبحث باز — بازآزمون ترمیمی بسازید ({'، '.join(sample)})",
            "due": d.isoformat(),
            "status": "needs_build",
            "highlight": "today" if d == today else None,
            "ref": {"type": "retest", "id": None},
        }
        by_date.setdefault(d, []).append(item)

    cycle = {
        "open_errors": len(errors),
        "topics": len(topics),
        "pending_exam": bool(
            [e for e in retest_exams if e.id not in attempted and _naive(e.closes_at).date() >= today]
        )
        if retest_exams
        else False,
    }
    return by_date, cycle


async def build_calendar(
    db: AsyncSession, student_user_id: int, start: date, end: date
) -> dict:
    """گروه‌بندی همه رویدادها به تفکیک روز: task/exam/period/retest/mission."""
    today = date.today()
    now = datetime.now().replace(microsecond=0)

    profile = await _profile(db, student_user_id)
    grade = profile.grade if profile else None

    task_map = await _student_task_map(db, student_user_id, end)
    visible, attempted, referenced = await _visible_exams(db, student_user_id, task_map)

    # ---- دوره‌ها (§4.1 دورهٔ ۱۴ روزه) ----
    periods = (
        (
            await db.execute(
                select(Period).where(Period.start_date <= end, Period.end_date >= start).order_by(Period.number)
            )
        )
        .scalars()
        .all()
    )
    period_topics = await _period_topics(db, {p.id for p in periods}, grade)

    # ---- آزمون/بازآزمون: بازهٔ روزهای هم‌پوشان ----
    exam_days: dict[date, list[dict]] = {}
    for e in visible:
        opens, closes = _naive(e.opens_at), _naive(e.closes_at)
        if opens is None:
            continue
        od, cd = opens.date(), (closes.date() if closes else opens.date())
        if od > end or cd < start:
            continue
        d = max(od, start)
        last = min(cd, end)
        while d <= last:
            exam_days.setdefault(d, []).append(
                _exam_item(e, d, now=now, today=today, attempted=e.id in attempted)
            )
            d = date.fromordinal(d.toordinal() + 1)

    retest_days, cycle = await _retest_cycle(
        db, student_user_id, start=start, end=end, today=today,
        visible=visible, attempted=attempted, referenced=referenced,
    )

    # ---- مأموریت روزانه + گروه‌بندی نهایی ----
    days: list[dict] = []
    mission_today: dict | None = None
    overdue_count = 0
    soon_exams = 0
    pending_today: list[PlanTask] = []
    d = start
    while d <= end:
        items: list[dict] = []

        # کارهای جا‌ماندهٔ قبل از بازه → روی «امروز» نمایش داده می‌شوند
        carried: list[PlanTask] = []
        if d == today:
            for od in sorted(k for k in task_map if k < start and k < today):
                for t in task_map[od]:
                    if t.status == "pending":
                        carried.append(t)
        day_tasks = carried + task_map.get(d, [])
        if d == today:
            pending_today = [t for t in day_tasks if t.status == "pending"]

        for t in carried:
            items.append(_task_item(t, today=today, carried=True))
        for t in task_map.get(d, []):
            items.append(_task_item(t, today=today, carried=False))

        items.extend(exam_days.get(d, []))

        for p in periods:
            if p.start_date <= d <= p.end_date:
                titles = period_topics.get(p.id, [])
                detail = f"مباحث این دوره: {'، '.join(titles)}" if titles else "برنامه استاندارد این دوره"
                if d == p.start_date:
                    detail = f"شروع دوره — {detail}"
                elif d == p.end_date:
                    detail = f"پایان دوره — {detail}"
                    if p.has_cumulative_exam:
                        detail += " · آزمون تجمعی بعد از این دوره"
                hl = "today" if d == today else None
                if hl is None and p.end_date >= today and (p.end_date - today) <= timedelta(hours=SOON_HOURS):
                    hl = "soon"
                items.append(
                    {
                        "kind": "period",
                        "title": f"دوره {fa_num(p.number)} ({p.academic_year})",
                        "detail": detail,
                        "due": p.end_date.isoformat(),
                        "status": "active",
                        "highlight": hl,
                        "ref": {"type": "period", "id": p.id},
                    }
                )

        items.extend(retest_days.get(d, []))

        mission = _mission_for(
            d, day_tasks, exam_days.get(d, []), today=today, free=is_free_day(d)
        )
        items.append(mission)
        if d == today:
            mission_today = mission

        for it in items:
            if it.get("highlight") == "overdue":
                overdue_count += 1

        days.append(
            {
                "date": d.isoformat(),
                "weekday": WEEKDAY_FA[d.weekday()],
                "is_today": d == today,
                "is_free_day": is_free_day(d),
                "items": items,
                "counts": {
                    kind: sum(1 for it in items if it["kind"] == kind)
                    for kind in sorted({it["kind"] for it in items})
                },
            }
        )
        d = date.fromordinal(d.toordinal() + 1)

    # خلاصهٔ نما
    for e in visible:
        opens, closes = _naive(e.opens_at), _naive(e.closes_at)
        if opens and closes and e.id not in attempted and opens <= now <= closes:
            if closes - now <= timedelta(hours=SOON_HOURS):
                soon_exams += 1

    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "today": today.isoformat(),
        "days": days,
        "mission": mission_today,
        "summary": {
            "pending_tasks": len(pending_today),
            "overdue": overdue_count,
            "exams_soon": soon_exams,
            "open_errors": cycle["open_errors"],
            "retest_pending": cycle["pending_exam"],
            "free_today": is_free_day(today),
            "suggested_minutes": 150 if is_free_day(today) else 60,
        },
        "note_fa": (
            "روز آزاد (پنجشنبه/جمعه): تمرین جامع، ترمیم خطاها و مرور فاصله‌دار؛ "
            "روزهای مدرسه بار سبک‌تری دارند (§4.2)."
        ),
    }


def _task_item(t: PlanTask, *, today: date, carried: bool) -> dict:
    title = TASK_TYPE_FA.get(t.task_type, t.task_type)
    topic_part = f" — مبحث {fa_num(t.topic_id)}" if t.topic_id else ""
    status = t.status
    hl = None
    if t.status == "pending":
        if t.for_date < today:
            hl = "overdue"
            status = "overdue"
        elif t.for_date == today:
            hl = "today"
        elif (t.for_date - today).days <= SOON_HOURS // 24:
            hl = "soon"
    elif t.status == "done" and t.for_date == today:
        hl = "today"
    detail = TASK_STATUS_FA.get(t.status, t.status) + f" · اولویت {fa_num(f'{t.priority:.2f}')}"
    if carried:
        detail = f"جا‌مانده از {t.for_date.isoformat()} — منتقل‌شده به امروز · {detail}"
    return {
        "kind": "task",
        "title": title + topic_part,
        "detail": detail,
        "due": t.for_date.isoformat(),
        "status": status,
        "highlight": hl,
        "ref": {"type": "task", "id": t.id},
    }


def _mission_for(
    d: date, tasks: list[PlanTask], exam_items: list[dict], *, today: date, free: bool
) -> dict:
    pending = [t for t in tasks if t.status == "pending"]
    pending.sort(key=lambda t: -t.priority)
    top = pending[:MISSION_MAX_TASKS]
    parts: list[str] = []
    if pending:
        parts.append(
            f"{fa_num(len(pending))} کار در اولویت: "
            + "، ".join(TASK_TYPE_FA.get(t.task_type, t.task_type) for t in top[:3])
        )
    upcoming_exams = [x for x in exam_items if x["kind"] in ("exam", "retest") and x["status"] != "done"]
    if upcoming_exams:
        parts.append(f"آزمون: {upcoming_exams[0]['title']}")
    parts.append(
        "روز آزاد — تمرین جامع، ترمیم خطاها و مرور فاصله‌دار"
        if free
        else "روز مدرسه — بار سبک: درس + تمرین کوتاه"
    )
    status = "pending" if pending else ("done" if tasks else "light")
    return {
        "kind": "mission",
        "title": ("مأموریت امروز" if d == today else f"مأموریت {WEEKDAY_FA[d.weekday()]}"),
        "detail": " · ".join(parts),
        "due": d.isoformat(),
        "status": status,
        "highlight": "today" if d == today else None,
        "ref": {"type": "mission", "id": None},
        "tasks": [
            {
                "id": t.id,
                "type": t.task_type,
                "title": TASK_TYPE_FA.get(t.task_type, t.task_type),
                "priority": t.priority,
                "topic_id": t.topic_id,
            }
            for t in top
        ],
        "free_day": free,
    }


# --------------------------------------------------------------------- exam history
async def _attempt_bundle(db: AsyncSession, student_user_id: int) -> tuple[list, dict, dict, dict, dict]:
    """تلاش‌های خودِ دانش‌آموز + آزمون‌ها/پاسخ‌ها/خطاها/حالت مباحث — فقط دادهٔ خودش."""
    attempts = (
        (
            await db.execute(
                select(ExamAttempt).where(ExamAttempt.student_user_id == student_user_id)
            )
        )
        .scalars()
        .all()
    )
    attempts.sort(
        key=lambda a: (_naive(a.submitted_at) or _naive(a.started_at) or datetime.min, a.id)
    )
    exam_ids = {a.exam_id for a in attempts}
    exams = {
        e.id: e
        for e in (
            (
                await db.execute(
                    select(Exam)
                    .options(selectinload(Exam.exam_items).selectinload(ExamItem.item))
                    .where(Exam.id.in_(exam_ids) if exam_ids else Exam.id == -1)
                )
            )
            .scalars()
            .all()
        )
    }
    attempt_ids = [a.id for a in attempts]
    answers: dict[int, list[AttemptAnswer]] = {}
    if attempt_ids:
        rows = (
            await db.execute(
                select(AttemptAnswer).where(AttemptAnswer.attempt_id.in_(attempt_ids))
            )
        ).scalars().all()
        for a in rows:
            answers.setdefault(a.attempt_id, []).append(a)
    answer_ids = [a.id for lst in answers.values() for a in lst]
    errors_by_answer: dict[int, ErrorRecord] = {}
    if answer_ids:
        errs = (
            await db.execute(select(ErrorRecord).where(ErrorRecord.attempt_answer_id.in_(answer_ids)))
        ).scalars().all()
        for e in errs:
            errors_by_answer[e.attempt_answer_id] = e
    states = {
        st.topic_id: st
        for st in (
            await db.execute(
                select(StudentTopicState).where(StudentTopicState.student_user_id == student_user_id)
            )
        ).scalars()
    }
    return attempts, exams, answers, errors_by_answer, states


def _attempt_row(
    attempt: ExamAttempt,
    *,
    exam: Exam | None,
    answers: list[AttemptAnswer],
    errors_by_answer: dict[int, ErrorRecord],
    states: dict[int, StudentTopicState],
    delta: float | None,
) -> dict:
    correct = sum(1 for a in answers if a.is_correct and a.selected_option)
    answered_rows = [a for a in answers if a.selected_option is not None]
    wrong = len(answered_rows) - correct
    # سؤال‌های بدون ردیف پاسخ (submit فقط سؤال‌های پاسخ‌داده‌شده را ردیف می‌کند)
    item_count = len(exam.exam_items) if exam else len(answers)
    unanswered = max(0, item_count - len(answered_rows))
    time_spent = sum(a.time_spent_ms or 0 for a in answers)
    err_ids = [errors_by_answer[a.id].id for a in answers if a.id in errors_by_answer]
    resolved = sum(
        1 for a in answers if a.id in errors_by_answer and errors_by_answer[a.id].status == "resolved"
    )
    k = exam.negative_marking_k if exam else 0.0
    penalty = 0.0
    if exam and k > 0:
        item_points = {ei.id: ei.points for ei in exam.exam_items}
        penalty = round(
            k * sum(item_points.get(a.exam_item_id, 1.0) for a in answers if a.selected_option and not a.is_correct),
            2,
        )

    topics: list[dict] = []
    if exam:
        seen: set[int] = set()
        for ei in exam.exam_items:
            q = ei.item
            if q is None or q.topic_id in seen:
                continue
            seen.add(q.topic_id)
            st = states.get(q.topic_id)
            topics.append(
                {
                    "topic_id": q.topic_id,
                    "status": status_of(st.effective_mastery, st.evidence_count) if st else "unknown",
                    "mastery": st.effective_mastery if st else None,
                }
            )

    return {
        "id": attempt.id,
        "exam_id": attempt.exam_id,
        "exam_title": exam.title_fa if exam else f"آزمون {attempt.exam_id}",
        "exam_type": exam.exam_type if exam else "practice",
        "subject": exam.subject if exam else None,
        "grade": exam.grade if exam else None,
        "status": attempt.status,
        "in_progress": attempt.status == "in_progress",
        "started_at": _naive(attempt.started_at).isoformat(sep=" ", timespec="seconds") if attempt.started_at else None,
        "submitted_at": _naive(attempt.submitted_at).isoformat(sep=" ", timespec="seconds") if attempt.submitted_at else None,
        "percent": attempt.percent,
        "raw_score": attempt.raw_score,
        "item_count": item_count,
        "correct": correct,
        "wrong": wrong,
        "unanswered": unanswered,
        "time_spent_ms": time_spent,
        "delta_percent": delta,
        "negative_marking": {
            "applied": bool(k and k > 0),
            "k": k or 0.0,
            "penalty": penalty,
        },
        "errors_recorded": len(err_ids),
        "errors_resolved": resolved,
        "topics": topics,
    }


async def exam_history(db: AsyncSession, student_user_id: int) -> dict:
    """تاریخچهٔ تحلیلی آزمون: هر تلاش با نمره/ترکیب پاسخ‌ها/تغییر نسبت به تلاش
    قبلی همان آزمون/وضعیت تسط مباحث/خطاهای ثبت‌شده و رفع‌شده + روند برای نمودار."""
    attempts, exams, answers, errors_by_answer, states = await _attempt_bundle(
        db, student_user_id
    )
    rows: list[dict] = []
    prev_percent: dict[int, float] = {}
    trend: list[dict] = []
    for i, a in enumerate(attempts, start=1):
        exam = exams.get(a.exam_id)
        ans = answers.get(a.id, [])
        delta = None
        if a.percent is not None and a.exam_id in prev_percent:
            delta = round(a.percent - prev_percent[a.exam_id], 2)
        row = _attempt_row(
            a,
            exam=exam,
            answers=ans,
            errors_by_answer=errors_by_answer,
            states=states,
            delta=delta,
        )
        row["index"] = i
        rows.append(row)
        if a.percent is not None:
            trend.append(
                {
                    "attempt_id": a.id,
                    "percent": a.percent,
                    "date": row["submitted_at"],
                    "label": f"تلاش {fa_num(i)}",
                }
            )
            prev_percent[a.exam_id] = a.percent

    graded = [r for r in rows if r["percent"] is not None]
    avg = round(sum(r["percent"] for r in graded) / len(graded), 2) if graded else None
    best = max((r["percent"] for r in graded), default=None)
    return {
        "attempts": rows,
        "trend": trend,
        "summary": {
            "attempts": len(rows),
            "graded": len(graded),
            "avg_percent": avg,
            "best_percent": best,
            "last_delta": graded[-1]["delta_percent"] if graded else None,
            "total_time_ms": sum(r["time_spent_ms"] for r in rows),
            "errors_recorded": sum(r["errors_recorded"] for r in rows),
            "errors_resolved": sum(r["errors_resolved"] for r in rows),
        },
    }


async def _mastery_at(evs: list[Evidence], at: datetime | None) -> tuple[float, float, int]:
    """(M, E, تعداد شواهد) در لحظهٔ `at` — با همان فرمول‌های SLM."""
    if not evs:
        return 0.0, 0.0, 0
    ref = at or datetime.now().replace(microsecond=0)
    s = get_settings()
    ordered = sorted(evs, key=lambda e: _naive(e.occurred_at) or datetime.min)
    s_val = float(s.stability_initial_days)
    recs: list[EvidenceRecord] = []
    for e in ordered:
        occ = _naive(e.occurred_at) or ref
        successful = e.partial_credit >= s.success_threshold
        s_val = next_stability(s_val, successful)
        recs.append(
            EvidenceRecord(
                weight=e.weight,
                difficulty=e.difficulty_weight,
                partial_credit=e.partial_credit,
                days_ago=max(0.0, (ref - occ).total_seconds() / 86400.0),
            )
        )
    m = mastery(recs)
    last_occ = _naive(ordered[-1].occurred_at) or ref
    r = retention(max(0.0, (ref - last_occ).total_seconds() / 86400.0), s_val)
    return m, effective_mastery(m, r), len(evs)


async def attempt_detail(db: AsyncSession, student_user_id: int, attempt_id: int) -> dict | None:
    """مرور سؤال‌به‌سؤال یک تلاش + دلتای تسط مبحث‌ها قبل/بعد (مالکیت: فقط خود دانش‌آموز)."""
    attempt = await db.get(ExamAttempt, attempt_id)
    if attempt is None or attempt.student_user_id != student_user_id:
        return None

    exam = (
        await db.execute(
            select(Exam)
            .options(selectinload(Exam.exam_items).selectinload(ExamItem.item))
            .where(Exam.id == attempt.exam_id)
        )
    ).scalar_one_or_none()

    answers = (
        await db.execute(select(AttemptAnswer).where(AttemptAnswer.attempt_id == attempt.id))
    ).scalars().all()
    ans_by_item = {a.exam_item_id: a for a in answers}
    answer_ids = [a.id for a in answers]
    errors_by_answer: dict[int, ErrorRecord] = {}
    if answer_ids:
        for e in (
            await db.execute(select(ErrorRecord).where(ErrorRecord.attempt_answer_id.in_(answer_ids)))
        ).scalars():
            errors_by_answer[e.attempt_answer_id] = e
    # همه خطاهای ثبت‌شده در همین تلاش. نکته: سرویس assessment پیوند
    # attempt_answer_id را با اندیس جواب‌ها می‌نویسد و اگر پاسخ درستی قبل از
    # پاسخ غلط باشد، پیوند جابه‌جا می‌شود — بنابراین خطا را با متنِ همان سؤال
    # تطبیق می‌دهیم تا نمایش مرور سؤال‌به‌سؤال درست بماند.
    attempt_errors = [errors_by_answer[i] for i in sorted(errors_by_answer)]

    def _find_record(question, ans: AttemptAnswer | None) -> ErrorRecord | None:
        if ans is not None and ans.id in errors_by_answer:
            rec = errors_by_answer[ans.id]
            if ((rec.item_snapshot or {}).get("body")) == question.body:
                return rec
        for rec in attempt_errors:
            if ((rec.item_snapshot or {}).get("body")) == question.body:
                return rec
        return None

    topic_ids = set()
    if exam:
        topic_ids = {ei.item.topic_id for ei in exam.exam_items if ei.item is not None}
    topics = {
        t.id: t for t in (await db.execute(select(Topic).where(Topic.id.in_(topic_ids) if topic_ids else Topic.id == -1))).scalars()
    }
    states = {
        st.topic_id: st
        for st in (
            await db.execute(
                select(StudentTopicState).where(StudentTopicState.student_user_id == student_user_id)
            )
        ).scalars()
    }

    questions: list[dict] = []
    if exam:
        # family_id گروه سؤال‌های هم‌ارز (§5.3) — اگر هنوز ثبت نشده، کلید مشتق‌شده
        from app.models.assessment import QuestionFamilyMember
        from app.services.assessment import CAUSE_FA, expected_time_ms, family_key_for

        fam_rows = (
            await db.execute(
                select(QuestionFamilyMember).where(
                    QuestionFamilyMember.item_id.in_([ei.item_id for ei in exam.exam_items])
                )
            )
        ).scalars()
        fam_map = {r.item_id: r.family_id for r in fam_rows}

        for ei in sorted(exam.exam_items, key=lambda x: x.order):
            q = ei.item
            if q is None:
                continue
            a = ans_by_item.get(ei.id)
            err = _find_record(q, a)
            cause = a.error_cause if a else None
            if a and not a.is_correct and cause is None:
                cause = err.cause if err and err.cause != "unclear" else "conceptual"
            # خطای ثبت‌شده فقط وقتی معتبر است که به همین سؤال تعلق داشته باشد
            if a is not None and a.is_correct:
                err = None
                cause = None
            snap = (err.item_snapshot or {}) if err else {}
            questions.append(
                {
                    "order": ei.order,
                    "exam_item_id": ei.id,
                    "body": q.body,
                    "options": q.options,
                    "points": ei.points,
                    "selected": a.selected_option if a else None,
                    "correct_option": q.correct_option,
                    "is_correct": bool(a.is_correct) if a else False,
                    "answered": a is not None and a.selected_option is not None,
                    "time_spent_ms": a.time_spent_ms if a else 0,
                    "confidence": a.confidence if a else None,
                    "answer_changes": a.answer_changes if a else 0,
                    "topic_id": q.topic_id,
                    "topic_title": topics[q.topic_id].title_fa if q.topic_id in topics else None,
                    "error_cause": cause,
                    # قطعیت تشخیص علت + برچسب «نامشخص» (§6.2)
                    "certainty": snap.get("certainty"),
                    "unclear": bool(snap.get("unclear")) if err is not None else False,
                    "predicted_cause": snap.get("predicted_cause"),
                    "cause_fa": CAUSE_FA.get(cause, cause) if cause else None,
                    "expected_time_ms": expected_time_ms(q.difficulty),
                    "family_id": fam_map.get(q.id) or family_key_for(q),
                    "error_record": (
                        {
                            "id": err.id,
                            "status": err.status,
                            "status_fa": ERROR_STATUS_FA.get(err.status, err.status),
                            "certainty": snap.get("certainty"),
                            "unclear": bool(snap.get("unclear")),
                            "declared_cause": snap.get("declared_cause"),
                        }
                        if err
                        else None
                    ),
                }
            )

    # ---- تسط مبحث‌ها: قبل از این تلاش در برابر بعد از آن ----
    submitted = _naive(attempt.submitted_at)
    this_answer_ids = set(answer_ids)
    topic_rows: list[dict] = []
    if topic_ids:
        evs = (
            await db.execute(
                select(Evidence)
                .where(
                    Evidence.student_user_id == student_user_id,
                    Evidence.topic_id.in_(topic_ids),
                )
                .order_by(Evidence.occurred_at)
            )
        ).scalars().all()
        by_topic: dict[int, list[Evidence]] = {}
        for e in evs:
            by_topic.setdefault(e.topic_id, []).append(e)
        for tid in sorted(topic_ids):
            all_evs = by_topic.get(tid, [])
            # «قبل»: شواهد پیش از این تلاش. شواهدِ همین تلاش دقیقاً هم‌زمان با
            # submitted_at ثبت می‌شوند، پس مقایسهٔ سخت‌گیرانه (<) آن‌ها را کنار می‌زند.
            before_evs = [
                e
                for e in all_evs
                if not (e.attempt_answer_id and e.attempt_answer_id in this_answer_ids)
                and (
                    submitted is None
                    or (_naive(e.occurred_at) or datetime.min) < submitted
                )
            ]
            _m, before_e, before_n = await _mastery_at(before_evs, submitted)
            st = states.get(tid)
            after_e = st.effective_mastery if st else 0.0
            after_n = st.evidence_count if st else 0
            topic_rows.append(
                {
                    "topic_id": tid,
                    "title": topics[tid].title_fa if tid in topics else f"مبحث {tid}",
                    "before_e": before_e,
                    "after_e": after_e,
                    "delta_e": round(after_e - before_e, 2),
                    "status_before": status_of(before_e, before_n),
                    "status_after": status_of(after_e, after_n) if st else "unknown",
                }
            )

    base = _attempt_row(
        attempt,
        exam=exam,
        answers=answers,
        errors_by_answer=errors_by_answer,
        states=states,
        delta=None,
    )
    # دلتای نمره نسبت به تلاش قبلی همین آزمون
    prev = (
        await db.execute(
            select(ExamAttempt)
            .where(
                ExamAttempt.student_user_id == student_user_id,
                ExamAttempt.exam_id == attempt.exam_id,
                ExamAttempt.id != attempt.id,
                ExamAttempt.percent.is_not(None),
            )
        )
    ).scalars().all()
    prev = [p for p in prev if (_naive(p.submitted_at) or datetime.min) <= (submitted or datetime.max)]
    if prev and attempt.percent is not None:
        p0 = max(prev, key=lambda p: _naive(p.submitted_at) or datetime.min)
        base["delta_percent"] = round(attempt.percent - p0.percent, 2)

    return {
        "attempt": base,
        "questions": questions,
        "topics_before_after": topic_rows,
        "causes": {
            k: sum(1 for q in questions if q["error_cause"] == k)
            for k in sorted({q["error_cause"] for q in questions if q["error_cause"]})
        },
    }


# ======================= بستهٔ محتوایی مبحث (§3.4) =======================
# صفحهٔ مبحث یک «بستهٔ محتوایی» ثابت و از پیش تولیدشده دارد: درس‌نامه (دو
# سطح)، نکات کلیدی، مثال‌های حل‌شده، اشتباهات رایج، تمرین پله‌ای، پرسش از
# هوش مصنوعی، پرسش از دبیر + آزمونکی که بدون قبولش «مطالعه شد» حساب نمی‌شود.

DIFFICULTY_FA = {"easy": "ساده", "medium": "متوسط", "hard": "دشوار"}
DIFFICULTY_RANK = {"easy": 0, "medium": 1, "hard": 2}
MINICHECK_COUNT = 3        # «یک آزمونک ۲ تا ۳ سؤالی» (§3.4)
MINICHECK_PASS_RATIO = 0.66


async def _topic_questions(db: AsyncSession, topic_id: int) -> list:
    """سؤال‌های فعال مبحث، به ترتیب پله‌ای: ساده ← متوسط ← دشوار (§3.4 تمرین پله‌ای)."""
    from app.models.assessment import QuestionItem

    rows = (
        await db.execute(
            select(QuestionItem).where(QuestionItem.topic_id == topic_id, QuestionItem.is_active == 1)
        )
    ).scalars().all()
    return sorted(rows, key=lambda q: (DIFFICULTY_RANK.get(q.difficulty or "medium", 1), q.id))


async def minicheck_items(db: AsyncSession, topic_id: int) -> list:
    """آزمونک ۲ تا ۳ سؤالی بعد از درس‌نامه — انتخاب قطعی و تکرارپذیر."""
    return (await _topic_questions(db, topic_id))[:MINICHECK_COUNT]


async def content_package(db: AsyncSession, student_user_id: int, topic_id: int) -> dict | None:
    """GET /student/topics/{id}/package — بستهٔ محتوایی مبحث (§3.4).

    همهٔ بخش‌ها از داده‌های موجود (کاتالوگ، بانک سؤال، دفترچه خطا، برنامه)
    ساخته می‌شوند؛ متن درس‌نامه فقط وقتی «منتشرشده» است برمی‌گردد، چون سند
    §3.5 می‌گوید محتوا از پیش تولید و بازبینی‌شده است (تولید در لحظه نداریم)."""
    from sqlalchemy import func as sa_func

    from app.models.assessment import AttemptAnswer, ExamItem, QuestionItem
    from app.models.catalog import Chapter, Prerequisite, Skill
    from app.models.slm import ErrorRecord, PlanTask
    from app.services.assessment import CAUSE_FA

    topic = await db.get(Topic, topic_id)
    if topic is None:
        return None
    chapter = await db.get(Chapter, topic.chapter_id)
    book = None
    if chapter is not None:
        book = await db.get(Book, chapter.book_id)

    skills = (
        (await db.execute(select(Skill).where(Skill.topic_id == topic_id).order_by(Skill.id)))
        .scalars().all()
    )
    questions = await _topic_questions(db, topic_id)
    ready = topic.content_status == "published"
    skills_text = "، ".join(s.title_fa for s in skills) if skills else "مهارت‌های ثبت‌شده در سیلابس"

    # ---- ۱) درس‌نامه: دو سطح از پیش ساخته‌شده (ساده / تکمیلی) ----
    pending_note = (
        "متن این بخش هنوز تولید یا بازبینی نشده است (§3.5 خط تولید محتوا)؛ "
        "تا انتشار، از نکات کلیدی، مثال‌ها و تمرین پله‌ای استفاده کن."
    )
    published_note = "نسخهٔ منتشرشده و بازبینی‌شده توسط کارشناس/دبیر (§3.5)."
    lessons = [
        {
            "key": "simple",
            "title_fa": "درس‌نامهٔ ساده",
            "ready": ready,
            "body": (
                f"«{topic.title_fa}» را ساده و کوتاه می‌خوانی: ایدهٔ اصلی و تعریف، "
                f"سه مثال سرراست، و بعد تمرین پله‌ای. مهارت‌های این مبحث: {skills_text}."
                if ready
                else None
            ),
            "note_fa": published_note if ready else pending_note,
        },
        {
            "key": "extended",
            "title_fa": "درس‌نامهٔ تکمیلی",
            "ready": ready,
            "body": (
                f"نسخهٔ تکمیلیِ «{topic.title_fa}»: مفاهیم عمیق‌تر، نکته‌های آزمونی و "
                f"ارتباط این مبحث با فصل‌های دیگر؛ برای مرور جدی مناسب است."
                if ready
                else None
            ),
            "note_fa": published_note if ready else pending_note,
        },
    ]

    # ---- ۲) نکات کلیدی: کارت خلاصه چند خطی (از مهارت‌های مبحث) ----
    key_points = [{"title_fa": s.title_fa, "skill_id": s.id} for s in skills]

    # ---- ۳) مثال‌های حل‌شده: سؤال + پاسخ درست + دلیل غلط بودن بقیه گزینه‌ها ----
    worked_examples = []
    for q in questions[:2]:
        distractors = q.distractor_causes or {}
        worked_examples.append(
            {
                "item_id": q.id,
                "body": q.body,
                "options": q.options,
                "correct_option": q.correct_option,
                "difficulty": q.difficulty,
                "difficulty_fa": DIFFICULTY_FA.get(q.difficulty or "medium", q.difficulty),
                "why_wrong": [
                    {"option": k, "cause": v, "cause_fa": CAUSE_FA.get(v, v)}
                    for k, v in distractors.items()
                    if k != q.correct_option
                ],
                "steps_fa": [
                    "صورت سؤال را با دقت بخوان و مجهول را مشخص کن.",
                    "روش حل مناسب را انتخاب کن (همین مبحث).",
                    f"گزینهٔ {q.correct_option} درست است؛ بقیه گزینه‌ها را با دلیل مقایسه کن.",
                ],
            }
        )

    # ---- ۴) اشتباهات رایج: دادهٔ تجمیعی خطاها + خطاهای باز خود دانش‌آموز ----
    cause_rows = (
        await db.execute(
            select(ErrorRecord.cause, sa_func.count())
            .where(ErrorRecord.topic_id == topic_id)
            .group_by(ErrorRecord.cause)
        )
    ).all()
    total_cause = sum(n for _, n in cause_rows) or 0
    common_mistakes = {
        "by_cause": [
            {
                "cause": c,
                "cause_fa": CAUSE_FA.get(c, c),
                "count": n,
                "share": round(100.0 * n / total_cause, 1) if total_cause else 0.0,
            }
            for c, n in sorted(cause_rows, key=lambda r: -r[1])
        ],
        "note_fa": (
            "بر اساس تحلیل خطای واقعی دانش‌آموزان (داده تجمیعی)؛ هرچه سیستم بیشتر "
            "استفاده شود این بخش دقیق‌تر می‌شود (§3.4)."
        ),
    }

    # ---- ۵) تمرین پله‌ای + نتیجهٔ آخرین تلاش خود دانش‌آموز ----
    item_ids = [q.id for q in questions]
    exam_items = (
        (await db.execute(select(ExamItem).where(ExamItem.item_id.in_(item_ids) if item_ids else ExamItem.id == -1)))
        .scalars().all()
    )
    ei_by_item = {ei.item_id: ei.id for ei in exam_items}
    last_result: dict[int, dict] = {}
    if exam_items:
        ans = (
            await db.execute(
                select(AttemptAnswer)
                .where(
                    AttemptAnswer.student_user_id == student_user_id,
                    AttemptAnswer.exam_item_id.in_([ei.id for ei in exam_items]),
                )
                .order_by(AttemptAnswer.id.desc())
            )
        ).scalars().all()
        for a in ans:
            qid = next((k for k, v in ei_by_item.items() if v == a.exam_item_id), None)
            if qid is not None and qid not in last_result:
                last_result[qid] = {"correct": bool(a.is_correct), "selected": a.selected_option}
    practice = {
        "items": [
            {
                "item_id": q.id,
                "body": q.body,
                "options": q.options,
                "difficulty": q.difficulty,
                "difficulty_fa": DIFFICULTY_FA.get(q.difficulty or "medium", q.difficulty),
                "last_result": last_result.get(q.id),
            }
            for q in questions
        ],
        "note_fa": "تمرین پله‌ای از ساده به دشوار؛ پاسخ درست را خودت بعد از تلاش با مثال حل‌شده مقایسه کن.",
    }

    # ---- ۶/۷) پرسش از هوش مصنوعی و پرسش از دبیر (نردبان کمک §10.1) ----
    resources = [
        {
            "key": "assistant",
            "title_fa": "پرسش از هوش مصنوعی",
            "href": "/assistant",
            "detail_fa": "متن همین مبحث به‌عنوان زمینه به دستیار داده می‌شود (§3.6).",
        },
        {
            "key": "teacher",
            "title_fa": "پرسش از دبیر",
            "detail_fa": "ارسال پرسش نوشتاری به کارتابل دبیر کالس (زمان پاسخ هدف: ۴۸ ساعت).",
        },
        {
            "key": "errors",
            "title_fa": "دفترچهٔ خطاهای این مبحث",
            "href": "/student/errors",
            "detail_fa": "خطاهای ثبت‌شده و وضعیت رفع آن‌ها (§6).",
        },
    ]

    # ---- پیش‌نیازها + وضعیت تسلط آن‌ها ----
    prereq_rows = (
        await db.execute(select(Prerequisite).where(Prerequisite.topic_id == topic_id))
    ).scalars().all()
    prereq_ids = [p.prereq_topic_id for p in prereq_rows]
    prereq_titles = {
        t.id: t
        for t in (
            await db.execute(select(Topic).where(Topic.id.in_(prereq_ids) if prereq_ids else Topic.id == -1))
        ).scalars()
    }
    states = {
        st.topic_id: st
        for st in (
            await db.execute(select(StudentTopicState).where(StudentTopicState.student_user_id == student_user_id))
        ).scalars()
    }
    from app.services.slm import status_of

    prerequisites = []
    for pid in prereq_ids:
        st = states.get(pid)
        pt = prereq_titles.get(pid)
        prerequisites.append(
            {
                "topic_id": pid,
                "title": pt.title_fa if pt else f"مبحث {pid}",
                "mastery": st.effective_mastery if st else None,
                "status": status_of(st.effective_mastery, st.evidence_count) if st else "unknown",
            }
        )

    # ---- آزمونک + وضعیت «مطالعه شد» (§3.4: بدون آزمونک، تیک درس نمی‌خورد) ----
    mc = await minicheck_items(db, topic_id)
    task_rows = (
        await db.execute(
            select(PlanTask).where(
                PlanTask.student_user_id == student_user_id,
                PlanTask.topic_id == topic_id,
                PlanTask.task_type == "lesson",
            )
        )
    ).scalars().all()
    lesson_task = next((t for t in task_rows if t.status == "done"), None)
    pending_task = next((t for t in task_rows if t.status == "pending"), None)

    return {
        "topic": {
            "id": topic.id,
            "title": topic.title_fa,
            "chapter": chapter.title_fa if chapter else None,
            "book": book.title_fa if book else None,
            "subject": book.subject if book else None,
            "period_id": topic.period_id,
            "blueprint_weight": topic.blueprint_weight,
            "content_status": topic.content_status,
            "state": (
                {
                    "mastery": states[topic_id].effective_mastery,
                    "status": status_of(states[topic_id].effective_mastery, states[topic_id].evidence_count),
                }
                if topic_id in states
                else {"mastery": None, "status": "unknown"}
            ),
        },
        "lessons": lessons,
        "key_points": key_points,
        "worked_examples": worked_examples,
        "common_mistakes": common_mistakes,
        "practice": practice,
        "prerequisites": prerequisites,
        "resources": resources,
        "minicheck": {
            "item_ids": [q.id for q in mc],
            "total": len(mc),
            "pass_ratio": MINICHECK_PASS_RATIO,
            "task_id": pending_task.id if pending_task else None,
            "note_fa": (
                "پس از درس‌نامه یک آزمونک ۲ تا ۳ سؤالی می‌آید و مطالعهٔ مبحث فقط "
                "با گذراندن آن در «پیشرفت در برنامه» حساب می‌شود (§3.4)."
            ),
        },
        "study": {
            "studied": lesson_task is not None and bool(lesson_task.minicheck_passed),
            "note_fa": "مطالعه‌شده ✓ — آزمونک را گذرانده‌اید." if lesson_task else "هنوز «مطالعه شد» نشده است؛ آزمونک را بزن.",
        },
    }


async def grade_minicheck(
    db: AsyncSession, student_user_id: int, topic_id: int, answers: list[dict]
) -> dict:
    """نمره‌دهی آزمونک مبحث (§3.4) — پاسخ‌ها سمت سرور با همان سؤال‌های
    بسته مقایسه می‌شوند؛ با قبول، کار «درس» همین مبحث انجام‌شده می‌شود و XP درس
    (§8.6) کسب می‌شود. خروجی: {passed, correct, total, message_fa, task_id}."""
    mc = await minicheck_items(db, topic_id)
    if not mc:
        return {
            "passed": False,
            "correct": 0,
            "total": 0,
            "task_id": None,
            "message_fa": "برای این مبحث سؤال فعالی وجود ندارد؛ آزمونک نمی‌توان ساخت.",
        }
    given = {int(a.get("item_id", 0)): a.get("selected") for a in answers if a.get("item_id")}
    correct = sum(1 for q in mc if given.get(q.id) == q.correct_option)
    total = len(mc)
    passed = (correct / total) >= MINICHECK_PASS_RATIO

    task_id = None
    if passed:
        from app.models.slm import PlanTask

        tasks = (
            await db.execute(
                select(PlanTask).where(
                    PlanTask.student_user_id == student_user_id,
                    PlanTask.topic_id == topic_id,
                    PlanTask.task_type == "lesson",
                    PlanTask.status == "pending",
                )
            )
        ).scalars().all()
        if tasks:
            task = min(tasks, key=lambda t: (abs((t.for_date - date.today()).days), -t.priority))
            task.status = "done"
            task.minicheck_passed = 1
            task_id = task.id
            await award_xp(
                db,
                student_user_id,
                "lesson_completed",
                ref_type="task",
                ref_id=task.id,
                topic_id=topic_id,
                detail_fa=f"گذراندن آزمونک مبحث {topic_id}",
            )

    return {
        "passed": passed,
        "correct": correct,
        "total": total,
        "task_id": task_id,
        "message_fa": (
            f"آزمونک قبول شد ({fa_num(correct)} از {fa_num(total)})؛ «مطالعه شد» ثبت شد."
            if passed
            else f"هنوز کافی نیست ({fa_num(correct)} از {fa_num(total)})؛ درس‌نامه را دوباره ببین و دوباره تلاش کن."
        ),
    }


# ================ سقف بار روزانه و توقف موقت (§4.3) ================
# سقف بر حسب دقیقه مطالعهٔ پیشنهادی هر پایه (جدول §4.2): بالای بازه = سقف.
DAILY_LOAD_CAPS: dict[str, dict[str, int]] = {
    "grade_10": {"school": 90, "free": 180},
    "grade_11": {"school": 120, "free": 240},
    "grade_12": {"school": 150, "free": 330},
}
DEFAULT_DAILY_CAP = {"school": 90, "free": 180}
# برآورد مدت هر نوع کار (دقیقه) — قابل بازنویسی با payload["minutes"]
TASK_MINUTES: dict[str, int] = {
    "lesson": 30,
    "practice": 30,
    "remedial_pack": 25,
    "spaced_review": 15,
    "retest": 20,
    "quiz": 15,
    "cumulative_prep": 30,
}
PAUSE_MAX_DAYS = 14  # «دانش‌آموز می‌تواند برنامه را تا ۱۴ روز متوقف کند» (§4.3)


def daily_cap_minutes(grade: str | None, day: date) -> int:
    """سقف بار روزانهٔ پایه در روز مدرسه / روز آزاد (§4.2 + §4.3)."""
    caps = DAILY_LOAD_CAPS.get(grade or "", DEFAULT_DAILY_CAP)
    return caps["free"] if is_free_day(day) else caps["school"]


def task_minutes(task: PlanTask) -> int:
    if isinstance(task.payload, dict) and task.payload.get("minutes"):
        try:
            return int(task.payload["minutes"])
        except (TypeError, ValueError):
            pass
    return TASK_MINUTES.get(task.task_type, 20)


def next_free_day(day: date) -> date:
    """روز آزادِ بعدی (پنجشнеж/جمعه §4.2) برای انتقال کارهای فراتر از سقف."""
    d = date.fromordinal(day.toordinal() + 1)
    while d.weekday() not in FREE_WEEKDAYS:
        d = date.fromordinal(d.toordinal() + 1)
    return d


async def active_pause(db: AsyncSession, student_user_id: int, today: date | None = None):
    """توقف موقت فعال این دانش‌آموز (§4.3) یا None."""
    today = today or date.today()
    rows = (
        await db.execute(
            select(PlanPause).where(
                PlanPause.student_user_id == student_user_id,
                PlanPause.status == "active",
                PlanPause.start_date <= today,
                PlanPause.end_date >= today,
            )
        )
    ).scalars().all()
    return max(rows, key=lambda p: p.start_date) if rows else None


def pause_message_fa(pause) -> str:
    return (
        f"برنامهٔ شما تا {pause.end_date.isoformat()} متوقف است"
        + (f" ({pause.reason_fa})" if pause.reason_fa else "")
        + "؛ در بازگشت یک برنامهٔ جبرانی فشرده ساخته می‌شود و زنجیرهٔ فعالیت‌تان نمی‌شکند."
    )


async def apply_daily_load_cap(
    db: AsyncSession, student_user_id: int, day: date | None = None
) -> dict:
    """سقف بار روزانه (§4.3): مجموع کارهای یک روز از سقف جدول بالا نمی‌گذرد؛
    اگر ترمیم/مرور بیشتر از ظرفیت بود، بر اساس اولویت نگه داشته می‌شود و
    بقیه به روز آزاد بعدی منتقل می‌شوند (با پیام فارسی توضیح).

    فقط کارهای «در انتظارِ» همان روز جابه‌جا می‌شوند؛ کارهای انجام‌شده در محاسبهٔ
    مصرف روز لحاظ می‌شوند. اگر توقف موقت فعال باشد، خودِ توقف حاکم است."""
    from app.models.plan_control import DailyLoadLog

    day = day or date.today()
    profile = await _profile(db, student_user_id)
    cap = daily_cap_minutes(profile.grade if profile else None, day)

    paused = await active_pause(db, student_user_id, day)
    tasks = (
        await db.execute(
            select(PlanTask).where(
                PlanTask.student_user_id == student_user_id,
                PlanTask.for_date == day,
                PlanTask.status.in_(["pending", "done"]),
            )
        )
    ).scalars().all()
    done_minutes = sum(task_minutes(t) for t in tasks if t.status == "done")
    pending = [t for t in tasks if t.status == "pending"]
    pending.sort(key=lambda t: -t.priority)

    remaining = max(0, cap - done_minutes)
    kept = 0
    movable: list[PlanTask] = []
    for t in pending:
        m = task_minutes(t)
        if kept + m <= remaining:
            kept += m
        else:
            movable.append(t)

    used = done_minutes + kept
    moved_ids: list[int] = []
    message_fa = None
    if movable and paused is None:
        target = next_free_day(day)
        reason = (
            f"بار امروز از سقف {fa_num(cap)} دقیقه فراتر می‌رفت؛ "
            f"{fa_num(len(movable))} کار کم‌اولویت بر اساس اولویت به روز آزاد "
            f"{target.isoformat()} منتقل شد (سقف بار روزانه §4.3)."
        )
        for t in movable:
            payload = dict(t.payload) if isinstance(t.payload, dict) else {}
            payload["moved_from"] = day.isoformat()
            payload["move_reason_fa"] = reason
            t.payload = payload
            t.for_date = target
            moved_ids.append(t.id)
        used += sum(task_minutes(t) for t in movable)
        message_fa = reason
        db.add(
            DailyLoadLog(
                student_user_id=student_user_id,
                day=day,
                cap_minutes=cap,
                used_minutes=used,
                moved_task_ids=moved_ids,
                message_fa=reason,
            )
        )
    elif movable:
        message_fa = (
            f"برنامه متوقف است؛ {fa_num(len(movable))} کار فراتر از سقف "
            f"{fa_num(cap)} دقیقه پس از پایان توقف بازآرایی می‌شود."
        )

    return {
        "date": day.isoformat(),
        "cap_minutes": cap,
        "used_minutes": used,
        "remaining_minutes": max(0, cap - used),
        "paused": paused is not None,
        "tasks": [
            {
                "id": t.id,
                "type": t.task_type,
                "type_fa": TASK_TYPE_FA.get(t.task_type, t.task_type),
                "minutes": task_minutes(t),
                "priority": t.priority,
                "moved": t.id in moved_ids,
            }
            for t in sorted(tasks, key=lambda x: -x.priority)
        ],
        "moved_task_ids": moved_ids,
        "cap_message_fa": message_fa,
        "note_fa": (
            "مجموع کارهای روز از سقف جدول پایه فراتر نمی‌رود؛ سلامت دانش‌آموز "
            "مقدم بر پوشش برنامه است (§4.3)."
        ),
    }


async def plan_control_status(db: AsyncSession, student_user_id: int) -> dict:
    """وضعیت کنترل برنامه: توقف موقت + سقف بار روزانه + دلیلِ توقف (§4.3)."""
    today = date.today()
    pause = await active_pause(db, student_user_id, today)
    load = await apply_daily_load_cap(db, student_user_id, today)
    if pause is not None:
        message_fa = pause_message_fa(pause)
    elif load.get("cap_message_fa"):
        message_fa = load["cap_message_fa"]
    else:
        message_fa = None
    return {
        "paused": pause is not None,
        "pause": (
            {
                "id": pause.id,
                "start_date": pause.start_date.isoformat(),
                "end_date": pause.end_date.isoformat(),
                "reason_fa": pause.reason_fa,
                "days_left": (pause.end_date - today).days,
            }
            if pause
            else None
        ),
        "message_fa": message_fa,
        "load": load,
        "note_fa": "سقف بار روزانه و توقف موقت (§4.3) — «برنامهٔ اصلی تغییر نمی‌کند؛ فقط کارهای شخصی اضافه می‌شوند».",
    }


async def pause_plan(
    db: AsyncSession, student_user_id: int, days: int | None = None, reason_fa: str | None = None
) -> dict:
    """توقف موقت برنامه (§4.3): حداکثر ۱۴ روز، حداکثر یک توقف فعال."""
    from app.models.plan_control import PlanPause

    today = date.today()
    current = await active_pause(db, student_user_id, today)
    if current is not None:
        return {
            "ok": True,
            "already_paused": True,
            "pause": {
                "start_date": current.start_date.isoformat(),
                "end_date": current.end_date.isoformat(),
                "days_left": (current.end_date - today).days,
            },
            "message_fa": pause_message_fa(current),
        }
    n = PAUSE_MAX_DAYS if days in (None, 0) else max(1, min(int(days), PAUSE_MAX_DAYS))
    pause = PlanPause(
        student_user_id=student_user_id,
        start_date=today,
        end_date=date.fromordinal(today.toordinal() + n - 1),
        reason_fa=(reason_fa or "").strip()[:200] or None,
        status="active",
    )
    db.add(pause)
    await db.flush()
    return {
        "ok": True,
        "already_paused": False,
        "pause": {
            "start_date": pause.start_date.isoformat(),
            "end_date": pause.end_date.isoformat(),
            "days_left": n,
        },
        "message_fa": pause_message_fa(pause),
    }


async def resume_plan(db: AsyncSession, student_user_id: int) -> dict:
    """پایان توقف + ساخت برنامهٔ جبرانی فشرده (§4.3): کارهای جا‌مانده در بازهٔ
    توقف، با احترام به سقف بار روزانه روی روزهای بعد پخش می‌شوند."""
    from app.models.plan_control import PlanPause

    today = date.today()
    pause = await active_pause(db, student_user_id, today)
    if pause is None:
        # شاید توقف تمام‌شده ولی برنامه هنوز جا‌مانده دارد
        any_pause = (
            await db.execute(
                select(PlanPause)
                .where(PlanPause.student_user_id == student_user_id, PlanPause.status == "active")
                .order_by(PlanPause.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if any_pause is None:
            return {"ok": False, "reason": "توقف فعالی برای ادامه وجود ندارد"}
        pause = any_pause

    pause.status = "finished"
    pause.finished_at = datetime.now()

    stranded = (
        await db.execute(
            select(PlanTask).where(
                PlanTask.student_user_id == student_user_id,
                PlanTask.status == "pending",
                PlanTask.for_date >= pause.start_date,
                PlanTask.for_date < today,
            )
        )
    ).scalars().all()

    profile = await _profile(db, student_user_id)
    plan_days = 0
    scheduled = 0
    if stranded:
        cursor = today
        budget = daily_cap_minutes(profile.grade if profile else None, cursor)
        used = 0
        for t in sorted(stranded, key=lambda x: (-x.priority, x.for_date)):
            m = task_minutes(t)
            if used + m > budget:
                plan_days += 1
                cursor = date.fromordinal(cursor.toordinal() + 1)
                budget = daily_cap_minutes(profile.grade if profile else None, cursor)
                used = 0
            payload = dict(t.payload) if isinstance(t.payload, dict) else {}
            payload["catchup_from"] = t.for_date.isoformat()
            t.payload = payload
            t.for_date = cursor
            used += m
            scheduled += 1
        plan_days += 1

    return {
        "ok": True,
        "resumed": True,
        "catchup": {
            "moved_tasks": scheduled,
            "days": plan_days,
            "message_fa": (
                f"برنامه از امروز ادامه می‌یابد؛ {fa_num(scheduled)} کار جا‌مانده در "
                f"{fa_num(max(plan_days, 1))} روز فشرده با احترام به سقف بار روزانه پخش شد."
                if scheduled
                else "برنامه از امروز ادامه می‌یابد؛ کار جا‌مانده‌ای برای پخش نبود."
            ),
        },
        "message_fa": "توقف موقت پایان یافت؛ زنجیرهٔ فعالیت شما حفظ شده است.",
    }


# ================= امتیاز، نشان‌ها و زنجیرهٔ مطالعه (§8.4 / §8.6 / §8.7) =================
# «فقط برای کار یادگیری واقعی» (§8.6) — باز کردن اپ یا صرفِ وقت امتیاز نمی‌دهد.
XP_ACTIONS: dict[str, int] = {
    "lesson_completed": 20,       # آزمونک درس گذرانده شد
    "practice_correct": 3,        # سؤال تمرین درست (سقف ۳۰ XP هر مبحث در روز)
    "remedial_pack_completed": 30,
    "retest_passed": 25,
    "spaced_review_done": 10,
    "period_exam_completed": 40,
    "helped_peer": 5,             # سقف ۲۵ XP در روز
}
XP_ACTION_FA: dict[str, str] = {
    "lesson_completed": "درس (آزمونک قبول)",
    "practice_correct": "تمرین درست",
    "remedial_pack_completed": "بستهٔ ترمیمی",
    "retest_passed": "بازآزمون قبول",
    "spaced_review_done": "مرور فاصله‌دار",
    "period_exam_completed": "آزمون دوره‌ای",
    "helped_peer": "کمک به هم‌گروهی",
}
XP_TOPIC_DAILY_CAP: dict[str, int] = {"practice_correct": 30}
XP_DAILY_CAP: dict[str, int] = {"helped_peer": 25}

# نگاشت کار برنامه ← رویداد امتیاز (کارهای بدون معادل در جدول §8.6 امتیاز ندارند)
TASK_XP_ACTION = {
    "lesson": "lesson_completed",
    "remedial_pack": "remedial_pack_completed",
    "spaced_review": "spaced_review_done",
    "retest": "retest_passed",
}


async def award_xp(
    db: AsyncSession,
    student_user_id: int,
    action: str,
    *,
    ref_type: str | None = None,
    ref_id: int | None = None,
    topic_id: int | None = None,
    detail_fa: str | None = None,
) -> dict:
    """ثبت امتیاز با رعایت سقف‌های ضدرگرفتگی §8.6 (هر رویداد یکبار برای همان
    ref، سقف روزانهٔ تمرین در هر مبحث). خروجی: {xp, action, total}."""
    from app.models.gamification import XpEvent

    base = XP_ACTIONS.get(action)
    if not base:
        return {"xp": 0, "action": action, "total": 0}
    today = date.today()

    # تکرار برای همان ref محسوب نمی‌شود (مثلاً دو بار ثبت همان آزمون)
    if ref_type and ref_id is not None:
        dup = (
            await db.execute(
                select(XpEvent).where(
                    XpEvent.student_user_id == student_user_id,
                    XpEvent.action == action,
                    XpEvent.ref_type == ref_type,
                    XpEvent.ref_id == ref_id,
                )
            )
        ).first()
        if dup is not None:
            total = (
                await db.execute(
                    select(sa_sum(XpEvent.xp)).where(XpEvent.student_user_id == student_user_id)
                )
            ).scalar() or 0
            return {"xp": 0, "action": action, "total": int(total), "deduped": True}

    xp = base
    topic_cap = XP_TOPIC_DAILY_CAP.get(action)
    if topic_cap is not None:
        used = (
            await db.execute(
                select(sa_sum(XpEvent.xp)).where(
                    XpEvent.student_user_id == student_user_id,
                    XpEvent.action == action,
                    XpEvent.day == today,
                    XpEvent.topic_id == topic_id,
                )
            )
        ).scalar() or 0
        if used + xp > topic_cap:
            xp = max(0, topic_cap - int(used))
    day_cap = XP_DAILY_CAP.get(action)
    if day_cap is not None and xp:
        used_day = (
            await db.execute(
                select(sa_sum(XpEvent.xp)).where(
                    XpEvent.student_user_id == student_user_id,
                    XpEvent.action == action,
                    XpEvent.day == today,
                )
            )
        ).scalar() or 0
        if used_day + xp > day_cap:
            xp = max(0, day_cap - int(used_day))

    if xp:
        db.add(
            XpEvent(
                student_user_id=student_user_id,
                day=today,
                action=action,
                xp=xp,
                ref_type=ref_type,
                ref_id=ref_id,
                topic_id=topic_id,
                detail_fa=detail_fa,
            )
        )
        await db.flush()

    total = (
        await db.execute(select(sa_sum(XpEvent.xp)).where(XpEvent.student_user_id == student_user_id))
    ).scalar() or 0
    return {"xp": xp, "action": action, "total": int(total)}


def compute_streak(active_days: set[date], paused_days: set[date], today: date) -> int:
    """زنجیرهٔ روزهای فعال متوالی (§8.7): روزهای توقف موقت شکننده نیستند —
    زنجیره از روزِ آخرین فعالیت به عقب می‌شمارد و روزهای توقف را جا نمی‌زند."""
    if not active_days:
        return 0
    d = today
    if d not in active_days and d not in paused_days:
        d = date.fromordinal(today.toordinal() - 1)
    streak = 0
    guard = 0
    while (d in active_days or d in paused_days) and guard < 3650:
        if d in active_days:
            streak += 1
        d = date.fromordinal(d.toordinal() - 1)
        guard += 1
    return streak


async def badge_list(db: AsyncSession, student_user_id: int) -> list[dict]:
    """نشان‌ها و تقدیر (§8.4): به رشد و رفتار یادگیری پاداش می‌دهند، نه نمرهٔ مطلق."""
    from app.models.gamification import XpEvent
    from app.models.slm import ErrorRecord, PlanTask
    from app.services.slm import normalized_gain

    attempts = (
        await db.execute(
            select(ExamAttempt).where(
                ExamAttempt.student_user_id == student_user_id,
                ExamAttempt.percent.is_not(None),
            )
        )
    ).scalars().all()
    attempts.sort(key=lambda a: (_naive(a.submitted_at) or _naive(a.started_at) or datetime.min, a.id))
    gain = None
    if len(attempts) >= 2:
        gain = normalized_gain(attempts[-1].percent, attempts[-2].percent)

    errors = (
        await db.execute(select(ErrorRecord).where(ErrorRecord.student_user_id == student_user_id))
    ).scalars().all()
    total_err = len(errors)
    resolved = [e for e in errors if e.status == "resolved"]
    relapsed = [e for e in errors if e.status == "relapsed" or e.relapsed_at is not None]
    stable = [e for e in resolved if e.relapsed_at is None]
    stable_pct = round(100.0 * len(stable) / total_err, 1) if total_err else 0.0

    since = date.fromordinal(date.today().toordinal() - 14)
    tasks = (
        await db.execute(
            select(PlanTask).where(
                PlanTask.student_user_id == student_user_id,
                PlanTask.for_date >= since,
            )
        )
    ).scalars().all()
    done_n = sum(1 for t in tasks if t.status == "done")
    missed_n = sum(
        1 for t in tasks if t.status == "missed" or (t.status == "pending" and t.for_date < date.today())
    )
    adherence = round(100.0 * done_n / (done_n + missed_n), 1) if (done_n + missed_n) else 0.0

    def _badge(key, title, desc, earned, pct):
        return {
            "key": key,
            "title_fa": title,
            "desc_fa": desc,
            "earned": bool(earned),
            "progress_pct": max(0.0, min(100.0, round(float(pct), 1))),
        }

    return [
        _badge(
            "progress_special",
            "پیشرفت ویژه",
            "رشد نرمال‌شده نسبت به آزمون قبل (g ≥ ۰٫۴)",
            gain is not None and gain >= 0.4,
            (gain or 0.0) / 0.4 * 100,
        ),
        _badge(
            "durable_master",
            "ماندگاری برتر",
            "بیشترین درصد خطاهای پایدار (رفع‌شده و برنگشته)",
            total_err >= 3 and stable_pct >= 60,
            stable_pct / 60 * 100,
        ),
        _badge(
            "no_repeat_error",
            "بدون خطای تکراری",
            "یک دورهٔ کامل بدون خطای بازگشته",
            total_err >= 3 and not relapsed and bool(resolved),
            100.0 if (total_err >= 3 and not relapsed and resolved) else (50.0 if not relapsed else 0.0),
        ),
        _badge(
            "plan_adherence",
            "مشارکت در برنامه",
            "پایبندی بالا به برنامه در دو هفتهٔ اخیر (≥ ۸۰٪)",
            (done_n + missed_n) >= 3 and adherence >= 80,
            adherence / 80 * 100,
        ),
    ]


async def xp_summary(db: AsyncSession, student_user_id: int) -> dict:
    """XP کل/امروز + زنجیرهٔ روزهای فعال + فهرست نشان‌ها + آخرین رویدادها (§8)."""
    from app.models.gamification import XpEvent
    from app.models.plan_control import PlanPause

    today = date.today()
    events = (
        (
            await db.execute(
                select(XpEvent)
                .where(XpEvent.student_user_id == student_user_id)
                .order_by(XpEvent.id.desc())
            )
        )
        .scalars()
        .all()
    )
    active_days = {e.day for e in events}
    pauses = (
        await db.execute(select(PlanPause).where(PlanPause.student_user_id == student_user_id))
    ).scalars().all()
    paused_days: set[date] = set()
    for p in pauses:
        d = p.start_date
        while d <= p.end_date:
            paused_days.add(d)
            d = date.fromordinal(d.toordinal() + 1)

    total = sum(e.xp for e in events)
    today_xp = sum(e.xp for e in events if e.day == today)
    return {
        "total_xp": total,
        "today_xp": today_xp,
        "streak": compute_streak(active_days, paused_days, today),
        "active_days": len(active_days),
        "badges": await badge_list(db, student_user_id),
        "actions_fa": XP_ACTION_FA,
        "recent": [
            {
                "action": e.action,
                "action_fa": XP_ACTION_FA.get(e.action, e.action),
                "xp": e.xp,
                "day": e.day.isoformat(),
                "detail_fa": e.detail_fa,
            }
            for e in events[:10]
        ],
        "note_fa": (
            "امتیاز فقط برای کار یادگیری واقعی است و جایگزین تسلط یا نمره نمی‌شود (§8.6)."
        ),
    }
