"""برنامه دوره‌ای/تقویم دانش‌آموز (student spec §4 «تقویم آموزشی و چرخه
دوهفته‌ای» + §13 «دورهٔ جاری: تقویم دوره، مباحث، روز آزمون، وضعیت ترمیم»)
و تاریخچهٔ تحلیلی آزمون (§7 «نظام ارزیابی» + §13 «آزمون‌ها / تحلیل و کارنامه»).

همه‌چیز از داده‌های موجود محاسبه می‌شود (Period/Topic/PlanTask/Exam/Attempt/
ErrorRecord/Evidence) — جدول جدیدی لازم نیست. همه برچسب‌ها فارسی‌اند و
آستانه‌ها از Settings می‌آیند؛ ثابت‌های نمایشیِ محلی همین ماژول‌اند."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.models.assessment import AttemptAnswer, Exam, ExamAttempt, ExamItem
from app.models.catalog import Book, Chapter, Period, Topic
from app.models.org import StudentProfile
from app.models.slm import ErrorRecord, Evidence, PlanTask, StudentTopicState
from app.services.slm import (
    EvidenceRecord,
    effective_mastery,
    mastery,
    next_stability,
    retention,
    status_of,
)

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
        for ei in sorted(exam.exam_items, key=lambda x: x.order):
            q = ei.item
            if q is None:
                continue
            a = ans_by_item.get(ei.id)
            err = _find_record(q, a)
            cause = a.error_cause if a else None
            if a and not a.is_correct and cause is None:
                cause = err.cause if err else "conceptual"
            # خطای ثبت‌شده فقط وقتی معتبر است که به همین سؤال تعلق داشته باشد
            if a is not None and a.is_correct:
                err = None
                cause = None
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
                    "error_record": (
                        {
                            "id": err.id,
                            "status": err.status,
                            "status_fa": ERROR_STATUS_FA.get(err.status, err.status),
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
