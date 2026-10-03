"""Student panel APIs (student spec §7, §3.3, §5, §6, §4.3)."""
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthUser, get_current_user
from app.core.config import get_settings
from app.core.db import get_db
from sqlalchemy.orm import selectinload

from app.models.assessment import AttemptAnswer, AttemptDraft, Exam, ExamAttempt, ExamItem
from app.models.catalog import Book, Chapter, Period, Topic
from app.models.content import TopicQuestion
from app.models.org import StudentProfile
from app.models.slm import ErrorRecord, PlanTask, StudentTopicState
from app.services import student_plan
from app.services.assessment import (
    CAUSE_FA as ERROR_CAUSE_FA,
    SECTION_FA,
    SIX_CAUSES,
    ensure_question_families,
    expected_time_ms,
    section_summary,
    assign_sections,
    submit_attempt,
)
from app.services.remediation import apply_retest_result, build_retest_exam, weak_topics_with_open_errors

router = APIRouter(prefix="/student", tags=["student"])


@router.get("/home")
async def home(current: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """سه شاخص اصلی: پیشرفت در برنامه، تسلط واقعی، خطاهای رفع‌شده (§7)."""
    s = get_settings()
    states = (
        await db.execute(select(StudentTopicState).where(StudentTopicState.student_user_id == current.id))
    ).scalars().all()

    # تسلط واقعی: میانگین وزن‌دار E روی مباحث تدریس‌شده (وزن بلوپرینت)
    topics = {
        t.id: t for t in (await db.execute(select(Topic))).scalars()
    }
    num = 0.0
    den = 0.0
    taught_any = False
    for st in states:
        t = topics.get(st.topic_id)
        if t is None:
            continue
        taught_any = True
        w = t.blueprint_weight or 1.0
        num += w * st.effective_mastery
        den += w
    mastery_pct = round(num / den, 1) if den else 0.0

    # خطاها
    errors = (
        await db.execute(select(ErrorRecord).where(ErrorRecord.student_user_id == current.id))
    ).scalars().all()
    total_errors = len(errors)
    resolved = sum(1 for e in errors if e.status in ("resolved", "relapsed") or e.status == "open" and False)
    resolved = sum(1 for e in errors if e.status == "resolved")

    # پیشرفت در برنامه (§4.4): P = 100 × Σ(u_k × completed_k) / Σ(u_k × due_k)
    # — فقط کارهای سررسیدشده تا امروز، با وزن واحدِ هر نوع کار؛ «درس» فقط وقتی
    # انجام می‌شود که آزمونکش گذشته باشد (§3.4). به جای نسبت سادهٔ تعداد.
    from app.services.slm import PLAN_TASK_UNIT, progress_in_plan

    tasks = (
        await db.execute(select(PlanTask).where(PlanTask.student_user_id == current.id))
    ).scalars().all()
    today = date.today()
    entries: list[tuple[str, bool, bool]] = []
    for t in tasks:
        unit = PLAN_TASK_UNIT.get(t.task_type)
        if unit is None:
            continue
        completed = t.status == "done" and (
            t.task_type != "lesson" or bool(t.minicheck_passed)
        )
        entries.append((unit, completed, t.for_date <= today))
    progress_pct = progress_in_plan(entries)

    next_exam = (
        await db.execute(
            select(Exam).where(Exam.status.in_(["published"]), Exam.exam_type.in_(["period_exam", "cumulative"]))
            .order_by(Exam.opens_at)
            .limit(1)
        )
    ).scalar_one_or_none()

    return {
        "progress_pct": progress_pct,
        "mastery_pct": mastery_pct,
        "gap": round(progress_pct - mastery_pct, 1),
        "errors_total": total_errors,
        "errors_resolved": resolved,
        "resolved_pct": round(100.0 * resolved / total_errors, 1) if total_errors else 0.0,
        "next_exam": {"id": next_exam.id, "title": next_exam.title_fa} if next_exam else None,
        "status_counts": _status_counts(states),
    }


def _status_counts(states) -> dict:
    counts = {"mastered": 0, "consolidating": 0, "weak": 0, "critical": 0, "unknown": 0}
    for st in states:
        counts[st.status if hasattr(st, "status") else "unknown"] = counts.get(
            _status_of_state(st), 0
        ) + 1
    return counts


def _status_of_state(st) -> str:
    from app.services.slm import status_of

    return status_of(st.effective_mastery, st.evidence_count)


@router.get("/books")
async def my_books(current: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """کتاب‌های کلاس من + درخت تسلط (§3.3)."""
    profile = (
        await db.execute(select(StudentProfile).where(StudentProfile.user_id == current.id))
    ).scalar_one_or_none()
    if profile is None:
        raise HTTPException(404, "پروفایل دانش‌آموز یافت نشد")

    # MVP: همه کتاب‌های پایه دانش‌آموز
    books = (await db.execute(select(Book).where(Book.grade == profile.grade))).scalars().all()
    states = {
        st.topic_id: st
        for st in (
            await db.execute(select(StudentTopicState).where(StudentTopicState.student_user_id == current.id))
        ).scalars()
    }
    from app.services.slm import status_of

    result = []
    for b in books:
        chapters = (await db.execute(select(Chapter).where(Chapter.book_id == b.id).order_by(Chapter.order))).scalars().all()
        ch_out = []
        for ch in chapters:
            topics = (await db.execute(select(Topic).where(Topic.chapter_id == ch.id).order_by(Topic.order))).scalars().all()
            t_out = []
            for t in topics:
                st = states.get(t.id)
                t_out.append(
                    {
                        "id": t.id,
                        "title": t.title_fa,
                        "period": t.period_id,
                        "mastery": st.mastery if st else None,
                        "effective_mastery": st.effective_mastery if st else None,
                        "status": status_of(st.effective_mastery, st.evidence_count) if st else "unknown",
                    }
                )
            ch_out.append({"id": ch.id, "title": ch.title_fa, "topics": t_out})
        result.append({"id": b.id, "title": b.title_fa, "subject": b.subject, "chapters": ch_out})
    return {"books": result}


@router.get("/exams")
async def exams(current: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(Exam)
            .options(selectinload(Exam.exam_items))
            .where(Exam.status == "published")
            .order_by(Exam.opens_at)
        )
    ).scalars().all()
    return {
        "exams": [
            {
                "id": e.id,
                "title": e.title_fa,
                "type": e.exam_type,
                "subject": e.subject,
                "grade": e.grade,
                "opens_at": e.opens_at,
                "closes_at": e.closes_at,
                "item_count": len(e.exam_items),
                # بخش‌های الف/ب آزمون تجمعی (§5.1)
                "sections": section_summary(e),
            }
            for e in rows
        ]
    }


@router.post("/exams/{exam_id}/start")
async def start_exam(exam_id: int, current: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    exam = (
        await db.execute(
            select(Exam).options(selectinload(Exam.exam_items).selectinload(ExamItem.item)).where(Exam.id == exam_id)
        )
    ).scalar_one_or_none()
    if exam is None or exam.status != "published":
        raise HTTPException(404, "آزمون یافت نشد یا فعال نیست")

    # شروع دوباره ⇐ ادامهٔ همان تلاش نیمه‌تمام (idempotent) — بدون ساخت
    # attempt یتیمِ in_progress که در تاریخچه جمع می‌شود.
    attempt = (
        await db.execute(
            select(ExamAttempt)
            .where(
                ExamAttempt.exam_id == exam.id,
                ExamAttempt.student_user_id == current.id,
                ExamAttempt.status == "in_progress",
            )
            .order_by(ExamAttempt.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    resumed = attempt is not None
    if attempt is None:
        attempt = ExamAttempt(exam_id=exam.id, student_user_id=current.id, status="in_progress")
        db.add(attempt)
        await db.commit()
        await db.refresh(attempt)

    # ---- آماده‌سازی سؤال‌ها (§5.1 / §5.3 / §5.6) ----
    items = sorted(exam.exam_items, key=lambda ei: ei.order)
    questions = [ei.item for ei in items if ei.item is not None]

    # گروه سؤال‌های هم‌ارز (family_id) — برای بازآزمون هرگز عین سؤال قبلی (§5.8)
    families = await ensure_question_families(db, questions)

    # بخش الف/ب: بخش ب از مباحث خطادارِ همین دانش‌آموز ساخته می‌شود (§5.1)
    error_topics = set(
        (
            await db.execute(
                select(ErrorRecord.topic_id).where(ErrorRecord.student_user_id == current.id)
            )
        ).scalars()
    )
    sections = assign_sections(exam, items, error_topics)

    # بازیابی ذخیرهٔ خودکار پاسخ‌ها (§5.6) — «ذخیرهٔ خودکار بعد از هر سؤال»
    drafts = {
        d.exam_item_id: d
        for d in (
            await db.execute(select(AttemptDraft).where(AttemptDraft.attempt_id == attempt.id))
        ).scalars()
    }

    out_items = []
    for ei in items:
        q = ei.item
        d = drafts.get(ei.id)
        section = sections.get(ei.id, "A")
        out_items.append(
            {
                "exam_item_id": ei.id,
                "order": ei.order,
                "body": ei.item.body,
                "options": ei.item.options,
                "points": ei.points,
                "difficulty": q.difficulty if q else None,
                # تایمر هر سؤال از دشواری ساخته می‌شود (§5.3 expected_time ← §5.6)
                "time_limit_s": max(1, expected_time_ms(q.difficulty if q else None) // 1000),
                "section": section,
                "section_title_fa": SECTION_FA.get(section, section),
                "counts_for_board": section == "A",
                "family_id": families.get(q.id) if q else None,
                "draft": (
                    {
                        "selected": d.selected,
                        "confidence": d.confidence,
                        "time_spent_ms": d.time_spent_ms,
                        "flagged_guess": bool(d.flagged_guess),
                        "marked": bool(d.marked),
                    }
                    if d
                    else None
                ),
            }
        )

    await db.commit()  # عضویت خانوادهٔ سؤال‌ها (idempotent) باید پایدار شود
    return {
        "attempt_id": attempt.id,
        "resumed": resumed,
        "saved_count": len(drafts),
        "total_time_s": sum(i["time_limit_s"] for i in out_items),
        "sections": section_summary(exam),
        "items": out_items,
    }


class DraftIn(BaseModel):
    exam_item_id: int
    selected: str | None = None
    confidence: int | None = None
    time_spent_ms: int = 0
    flagged_guess: bool = False
    marked: bool = False


class SaveIn(BaseModel):
    answers: list[DraftIn] = []


@router.post("/exams/{exam_id}/save")
async def save_exam_draft(
    exam_id: int,
    body: SaveIn,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """ذخیرهٔ خودکارِ پاسخ‌های در جریان + علامت‌گذاری «برای بازبینی» (§5.6).

    upsert روی کلید (تلاش × سؤال) ⇒ ارسال دوبارهٔ یک پاسخ بی‌اثر است و با
    تأیید نهایی، دقیقاً همین داده‌ها به ثبت پاسخ نهایی تبدیل می‌شوند."""
    attempt = (
        await db.execute(
            select(ExamAttempt)
            .where(
                ExamAttempt.exam_id == exam_id,
                ExamAttempt.student_user_id == current.id,
                ExamAttempt.status == "in_progress",
            )
            .order_by(ExamAttempt.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if attempt is None:
        raise HTTPException(400, "ابتدا آزمون را شروع کنید")

    valid = set(
        (
            await db.execute(select(ExamItem.id).where(ExamItem.exam_id == exam_id))
        ).scalars()
    )
    existing = {
        d.exam_item_id: d
        for d in (
            await db.execute(select(AttemptDraft).where(AttemptDraft.attempt_id == attempt.id))
        ).scalars()
    }
    saved = 0
    for a in body.answers:
        if a.exam_item_id not in valid:
            continue
        d = existing.get(a.exam_item_id)
        if d is None:
            d = AttemptDraft(
                attempt_id=attempt.id,
                exam_item_id=a.exam_item_id,
                student_user_id=current.id,
                selected=a.selected,
                confidence=a.confidence,
                time_spent_ms=a.time_spent_ms,
                flagged_guess=1 if a.flagged_guess else 0,
                marked=1 if a.marked else 0,
            )
            db.add(d)
        else:
            d.selected = a.selected
            d.confidence = a.confidence
            d.time_spent_ms = a.time_spent_ms
            d.flagged_guess = 1 if a.flagged_guess else 0
            d.marked = 1 if a.marked else 0
        saved += 1
    await db.commit()
    return {
        "ok": True,
        "saved": saved,
        "attempt_id": attempt.id,
        "message_fa": "پاسخ‌ها ذخیره شد؛ بین سؤال‌ها جابه‌جا شوید و نگران از دست رفتن پاسخ نباشید.",
    }



# NOTE: endpoints commit via db.commit() — get_db closes the session


class AnswerIn(BaseModel):
    exam_item_id: int
    selected: str | None = None
    confidence: int | None = None
    time_spent_ms: int = 0
    answer_changes: int = 0
    flagged_guess: bool = False


class SubmitIn(BaseModel):
    answers: list[AnswerIn]


@router.post("/exams/{exam_id}/submit")
async def submit_exam(exam_id: int, body: SubmitIn, current: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    exam = await db.get(Exam, exam_id)
    if exam is None:
        raise HTTPException(404, "آزمون یافت نشد")
    # تلاشِ در جریان مقدم است؛ در نبود آن، آخرین تلاش (برای پیام خطای شفاف)
    attempt = (
        await db.execute(
            select(ExamAttempt)
            .where(
                ExamAttempt.exam_id == exam_id,
                ExamAttempt.student_user_id == current.id,
                ExamAttempt.status == "in_progress",
            )
            .order_by(ExamAttempt.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if attempt is None:
        attempt = (
            await db.execute(
                select(ExamAttempt)
                .where(ExamAttempt.exam_id == exam_id, ExamAttempt.student_user_id == current.id)
                .order_by(ExamAttempt.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    if attempt is None:
        raise HTTPException(400, "ابتدا آزمون را شروع کنید")
    if attempt.status != "in_progress":
        raise HTTPException(409, "این آزمون قبلاً ثبت شده است")

    result = await submit_attempt(db, exam=exam, attempt=attempt, answers=[a.model_dump() for a in body.answers])

    # چرخه ترمیم/بازآزمون (فاز ۴): نتیجه بازآزمون، وضعیت دفترچه خطا را جابه‌جا می‌کند
    if exam.exam_type == "remedial_retest":
        attempt_answers = (
            await db.execute(select(AttemptAnswer).where(AttemptAnswer.attempt_id == attempt.id))
        ).scalars().all()
        result["remediation"] = await apply_retest_result(
            db, student_user_id=current.id, attempt=attempt, answers=attempt_answers
        )

    # ---- امتیاز یادگیری (§8.6) — فقط برای کار واقعی، بدون امتیاز تکراری ----
    result["xp"] = await _award_exam_xp(db, exam=exam, attempt=attempt, result=result)

    # ذخیرهٔ خودکارِ این تلاش دیگر لازم نیست (تلاش تمام شده است)
    await db.execute(delete(AttemptDraft).where(AttemptDraft.attempt_id == attempt.id))

    await db.commit()
    return result


async def _award_exam_xp(db: AsyncSession, *, exam: Exam, attempt: ExamAttempt, result: dict) -> list[dict]:
    """XP آزمون (§8.6): آزمون دوره‌ای/تجمعی ۴۰، بازآزمون قبول ۲۵ و هر پاسخ
    درستِ تمرین/کوییز ۳ (با سقف ۳۰ XP هر مبحث در روز). تکرار برای همان تلاش
    یا همان پاسخ، امتیاز ندارد."""
    events: list[dict] = []

    def _keep(ev: dict) -> None:
        if ev.get("xp"):
            events.append(ev)

    if exam.exam_type in ("period_exam", "cumulative"):
        _keep(
            await student_plan.award_xp(
                db,
                attempt.student_user_id,
                "period_exam_completed",
                ref_type="attempt",
                ref_id=attempt.id,
                detail_fa=f"شرکت در آزمون «{exam.title_fa}»",
            )
        )
    elif exam.exam_type == "remedial_retest":
        s = get_settings()
        remediation = result.get("remediation") or {}
        passed = bool(remediation.get("resolved")) or (attempt.percent or 0) >= (
            s.retest_pass_ratio * 100
        )
        if passed:
            _keep(
                await student_plan.award_xp(
                    db,
                    attempt.student_user_id,
                    "retest_passed",
                    ref_type="attempt",
                    ref_id=attempt.id,
                    detail_fa=f"قبولی در بازآزمون «{exam.title_fa}»",
                )
            )
    else:
        # سؤال‌های درستِ تمرین/کوییز — ۳ XP به ازای هر پاسخ درستِ همان مبحث
        ei_rows = (
            await db.execute(
                select(ExamItem)
                .options(selectinload(ExamItem.item))
                .where(ExamItem.exam_id == exam.id)
            )
        ).scalars().all()
        topic_by_ei = {ei.id: (ei.item.topic_id if ei.item else None) for ei in ei_rows}
        answers = (
            await db.execute(select(AttemptAnswer).where(AttemptAnswer.attempt_id == attempt.id))
        ).scalars().all()
        for a in answers:
            if not a.is_correct:
                continue
            _keep(
                await student_plan.award_xp(
                    db,
                    attempt.student_user_id,
                    "practice_correct",
                    ref_type="answer",
                    ref_id=a.id,
                    topic_id=topic_by_ei.get(a.exam_item_id),
                    detail_fa=f"پاسخ درست در «{exam.title_fa}»",
                )
            )
    return events


@router.get("/retest/plan")
async def retest_plan(current: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """برنامه بازآزمون ترمیمی: مباحث دارای خطای باز + دکمه ساخت آزمون (فاز ۴)."""
    targets = await weak_topics_with_open_errors(db, current.id)
    return {
        "targets": targets,
        "can_build": bool(targets),
        "note_fa": "بازآزمون ترمیمی فقط از مباحث دارای خطای باز ساخته می‌شود؛ پاسخ درست ⇒ رفع خطا، نادرست ⇒ بازگشت خطا.",
    }


@router.post("/retest/build")
async def retest_build(current: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await build_retest_exam(db, current.id)
    if not result.get("ok"):
        raise HTTPException(400, result.get("reason"))
    await db.commit()
    return result


@router.get("/errors")
async def error_notebook(current: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """دفترچه خطا (§6) + قطعیت تشخیص علت و برچسب «نامشخص» (§6.2)."""
    rows = (
        await db.execute(select(ErrorRecord).where(ErrorRecord.student_user_id == current.id).order_by(ErrorRecord.created_at.desc()))
    ).scalars().all()
    by_cause: dict[str, int] = {}
    errors = []
    for r in rows:
        by_cause[r.cause] = by_cause.get(r.cause, 0) + 1
        snap = r.item_snapshot if isinstance(r.item_snapshot, dict) else {}
        certainty = snap.get("certainty")
        unclear = r.cause == "unclear" or bool(snap.get("unclear"))
        errors.append(
            {
                "id": r.id,
                "topic_id": r.topic_id,
                "cause": r.cause,
                "cause_fa": ERROR_CAUSE_FA.get(r.cause, r.cause),
                # پیش‌بینی سیستم وقتی برچسب «نامشخص» ثبت شده یا دانش‌آموز علت را
                # خودش اعلام کرده است (§6.2 «قطعیت زیر ۰٫۵ ⇒ از شما پرسیده می‌شود»)
                "predicted_cause": snap.get("predicted_cause"),
                "declared_cause": snap.get("declared_cause"),
                "certainty": certainty,
                "unclear": unclear,
                "needs_reflection": unclear and not snap.get("declared_cause"),
                "status": r.status,
                "item": r.item_snapshot,
                "created_at": r.created_at,
            }
        )
    return {
        "errors": errors,
        "by_cause": by_cause,
        "six_causes_fa": {c: ERROR_CAUSE_FA.get(c, c) for c in SIX_CAUSES},
        "note_fa": (
            "هر خطا علت، قطعیت تشخیص و وضعیت رفع دارد؛ اگر برچسب «نامشخص» دیدید، "
            "علت را خودتان اعلام کنید تا برنامهٔ ترمیمی دقیق شود (§6.2)."
        ),
    }


class ReflectIn(BaseModel):
    cause: str


@router.post("/errors/{error_id}/reflect")
async def reflect_error(
    error_id: int,
    body: ReflectIn,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """اعلام علت خطا توسط خود دانش‌آموز (§6.2): وقتی قطعیت تشخیص کم است،
    برچسب «نامشخص» می‌خورد و اینجا علت نهایی را دانش‌آموز تعیین می‌کند."""
    err = await db.get(ErrorRecord, error_id)
    if err is None or err.student_user_id != current.id:
        raise HTTPException(404, "خطا یافت نشد")
    cause = (body.cause or "").strip()
    if cause not in SIX_CAUSES:
        raise HTTPException(400, "علت باید یکی از شش علت دفترچهٔ خطا باشد")
    snap = dict(err.item_snapshot) if isinstance(err.item_snapshot, dict) else {}
    snap["previous_cause"] = err.cause
    snap["declared_cause"] = cause
    snap["declared_at"] = datetime.now(timezone.utc).isoformat()
    err.item_snapshot = snap
    err.cause = cause
    await db.commit()
    return {
        "ok": True,
        "id": err.id,
        "cause": err.cause,
        "cause_fa": ERROR_CAUSE_FA.get(cause, cause),
        "certainty": snap.get("certainty"),
        "message_fa": f"علت خطا ثبت شد: {ERROR_CAUSE_FA.get(cause, cause)}؛ برنامهٔ ترمیمی بر همین اساس می‌نشیند.",
    }


@router.get("/tasks")
async def my_tasks(current: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # سقف بار روزانه + توقف موقت (§4.3): کارهای فراتر از سقف به روز آزاد بعدی
    # منتقل می‌شوند؛ فقط در صورت جابه‌جایی، تغییر ذخیره می‌شود.
    load = await student_plan.apply_daily_load_cap(db, current.id)
    if load.get("moved_task_ids"):
        await db.commit()
    pause = await student_plan.active_pause(db, current.id)
    rows = (
        await db.execute(select(PlanTask).where(PlanTask.student_user_id == current.id).order_by(PlanTask.priority.desc()))
    ).scalars().all()
    return {
        "tasks": [
            {
                "id": t.id,
                "type": t.task_type,
                "topic_id": t.topic_id,
                "for_date": t.for_date,
                "priority": t.priority,
                "status": t.status,
                "payload": t.payload,
                "minutes": student_plan.task_minutes(t),
            }
            for t in rows
        ],
        # کنترل بار برنامه (§4.3)
        "paused": pause is not None,
        "pause": (
            {
                "start_date": pause.start_date.isoformat(),
                "end_date": pause.end_date.isoformat(),
                "reason_fa": pause.reason_fa,
                "days_left": (pause.end_date - date.today()).days,
            }
            if pause
            else None
        ),
        "load": load,
        "message_fa": (
            student_plan.pause_message_fa(pause) if pause else load.get("cap_message_fa")
        ),
    }


class TaskDoneIn(BaseModel):
    minicheck_passed: bool = False


@router.post("/tasks/{task_id}/complete")
async def complete_task(task_id: int, body: TaskDoneIn, current: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    task = await db.get(PlanTask, task_id)
    if task is None or task.student_user_id != current.id:
        raise HTTPException(404, "کار یافت نشد")
    # توقف موقت ⇒ انجام کار ثبت نمی‌شود (§4.3)
    pause = await student_plan.active_pause(db, current.id)
    if pause is not None:
        raise HTTPException(409, student_plan.pause_message_fa(pause))
    # «مطالعه شد» فقط با گذراندن آزمونک (§4.3)
    if task.task_type == "lesson" and not body.minicheck_passed:
        raise HTTPException(400, "برای تیک درس باید آزمونک را بگذرانید")
    task.status = "done"
    task.minicheck_passed = 1 if body.minicheck_passed else 0
    # امتیاز کار یادگیری (§8.6) — کارهای بدون معادل در جدول امتیاز ندارند
    xp = None
    action = student_plan.TASK_XP_ACTION.get(task.task_type)
    if action:
        xp = await student_plan.award_xp(
            db,
            current.id,
            action,
            ref_type="task",
            ref_id=task.id,
            topic_id=task.topic_id,
            detail_fa=f"انجام کار «{student_plan.TASK_TYPE_FA.get(task.task_type, task.task_type)}»",
        )
    await db.commit()
    return {"ok": True, "xp": xp}


def _parse_day(value: str | None, name: str) -> date | None:
    """پارامتر تاریخ ISO (YYYY-MM-DD)؛ نامعتبر ⇒ 400 با پیام فارسی."""
    if value is None or value == "":
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(400, f"تاریخ نامعتبر برای پارامتر «{name}» (قالب YYYY-MM-DD)")


@router.get("/calendar")
async def calendar(
    from_date: str | None = Query(None, alias="from", description="تاریخ شروع بازه (YYYY-MM-DD)"),
    to_date: str | None = Query(None, alias="to", description="تاریخ پایان بازه (YYYY-MM-DD)"),
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """تقویم / برنامه دوره‌ای (§4 «تقویم آموزشی و چرخه دوهفته‌ای» + §13 «دوره جاری»).

    گروه‌بندی به تفکیک روز با رویدادهای kind ∈ task/exam/period/retest/mission؛
    هایلایت: امروز، سررسید گذشته (overdue) و سررسید تا ۴۸ ساعت آینده (soon)."""
    start = _parse_day(from_date, "from") or date.today()
    end = _parse_day(to_date, "to") or (start + timedelta(days=student_plan.CALENDAR_DEFAULT_DAYS - 1))
    if end < start:
        raise HTTPException(400, "تاریخ پایان بازه باید بعد از تاریخ شروع باشد")
    if (end - start).days + 1 > student_plan.CALENDAR_MAX_DAYS:
        raise HTTPException(
            400,
            f"بازه تقویم حداکثر {student_plan.fa_num(student_plan.CALENDAR_MAX_DAYS)} روز است",
        )
    return await student_plan.build_calendar(db, current.id, start, end)


@router.get("/exam-history")
async def exam_history(current: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """تاریخچه تحلیلی آزمون (§7 + §13 «تحلیل و کارنامه»): هر تلاش با نمره،
    ترکیب صحیح/غلط/نزده، نمره منفی، زمان، تغییر نسبت به تلاش قبلیِ همان آزمون،
    وضعیت تسط مباحث و خطاهای ثبت‌شده/رفع‌شده — فقط تلاش‌های خود دانش‌آموز."""
    return await student_plan.exam_history(db, current.id)


@router.get("/exam-history/{attempt_id}")
async def exam_attempt_review(
    attempt_id: int,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """مرور تک‌تلاش: سؤال‌به‌سؤال (پاسخ من، پاسخ صحیح، علت خطا از ۶ علت) +
    دلتای تسط مبحث‌ها قبل/بعد از آزمون. متعلق به دانش‌آموز دیگر ⇒ 404."""
    detail = await student_plan.attempt_detail(db, current.id, attempt_id)
    if detail is None:
        raise HTTPException(404, "تلاش آزمون یافت نشد")
    return detail


@router.get("/schedule")
async def my_schedule(
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """برنامه هفتگی کلاس دانش‌آموز — همان ردیف‌هایی که مدیر مدرسه ثبت کرده
    (همگام‌سازی: یک منبع حقیقت برای همه پنل‌ها). بدون کلاس → خالی."""
    from app.services import school_ops

    return await school_ops.student_schedule(db, current.id)


# ================= بستهٔ محتوایی مبحث (§3.4) =================


@router.get("/topics/{topic_id}/package")
async def topic_package(
    topic_id: int,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """بستهٔ محتوایی مبحث: درس‌نامهٔ دوسطح، نکات کلیدی، مثال حل‌شده، اشتباهات
    رایج، تمرین پله‌ای، پیش‌نیازها، پرسش از دبیر/هوش مصنوعی و آزمونک (§3.4)."""
    pkg = await student_plan.content_package(db, current.id, topic_id)
    if pkg is None:
        raise HTTPException(404, "مبحث یافت نشد")
    # پرسش‌های خودم از دبیر دربارهٔ همین مبحث (نردبان کمک §10.1)
    pkg["my_questions"] = [
        {
            "id": q.id,
            "body": q.body,
            "status": q.status,
            "created_at": q.created_at,
            "answered_at": q.answered_at,
        }
        for q in (
            await db.execute(
                select(TopicQuestion)
                .where(
                    TopicQuestion.student_user_id == current.id,
                    TopicQuestion.topic_id == topic_id,
                )
                .order_by(TopicQuestion.id.desc())
            )
        ).scalars()
    ]
    return pkg


class MinicheckIn(BaseModel):
    answers: list[dict] = []  # [{item_id, selected}]


@router.post("/topics/{topic_id}/minicheck")
async def topic_minicheck(
    topic_id: int,
    body: MinicheckIn,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """آزمونک ۲ تا ۳ سؤالی مبحث (§3.4): با قبول، کار «درس» همین مبحث انجام
    شده و در پیشرفت برنامه حساب می‌شود (بدون قبول، تیک درس نمی‌خورد)."""
    if await db.get(Topic, topic_id) is None:
        raise HTTPException(404, "مبحث یافت نشد")
    result = await student_plan.grade_minicheck(db, current.id, topic_id, body.answers)
    await db.commit()
    return result


class AskTeacherIn(BaseModel):
    body: str


@router.post("/topics/{topic_id}/ask-teacher")
async def ask_teacher(
    topic_id: int,
    body: AskTeacherIn,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """پرسش نوشتاری از دبیر کالس دربارهٔ همین مبحث (§3.4 + §10.1) — وارد
    کارتابل دبیر می‌شود؛ پاسخ در همین صفحه نمایش داده می‌شود."""
    if await db.get(Topic, topic_id) is None:
        raise HTTPException(404, "مبحث یافت نشد")
    text = (body.body or "").strip()
    if not text:
        raise HTTPException(400, "متن پرسش خالی است")
    profile = (
        await db.execute(select(StudentProfile).where(StudentProfile.user_id == current.id))
    ).scalar_one_or_none()
    row = TopicQuestion(
        student_user_id=current.id,
        topic_id=topic_id,
        class_id=profile.class_id if profile else None,
        body=text[:2000],
        status="sent",
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {
        "ok": True,
        "question": {"id": row.id, "body": row.body, "status": row.status, "created_at": row.created_at},
        "message_fa": "پرسش شما برای دبیر کالس ارسال شد (زمان پاسخ هدف: ۴۸ ساعت).",
    }


# ============ سقف بار روزانه و توقف موقت (§4.3) ============


@router.get("/plan/status")
async def plan_status(current: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """وضعیت کنترل برنامه: توقف موقت، سقف بار روزانه و پیام فارسی (§4.3)."""
    status = await student_plan.plan_control_status(db, current.id)
    if status["load"].get("moved_task_ids"):
        await db.commit()  # جابه‌جایی کارها باید پایدار بماند
    return status


class PauseIn(BaseModel):
    days: int | None = None
    reason_fa: str | None = None


@router.post("/plan/pause")
async def plan_pause(
    body: PauseIn,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """توقف موقت برنامه (§4.3): حداکثر ۱۴ روز؛ زنجیرهٔ فعالیت نمی‌شکند."""
    result = await student_plan.pause_plan(db, current.id, days=body.days, reason_fa=body.reason_fa)
    await db.commit()
    return result


@router.post("/plan/resume")
async def plan_resume(current: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """پایان توقف + برنامهٔ جبرانی فشرده با احترام به سقف بار روزانه (§4.3)."""
    result = await student_plan.resume_plan(db, current.id)
    if not result.get("ok"):
        raise HTTPException(400, result.get("reason") or "توقف فعالی وجود ندارد")
    await db.commit()
    return result


# ================= امتیاز، نشان و زنجیرهٔ مطالعه (§8) =================


@router.get("/xp")
async def xp_summary(current: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """XP کل/امروز، زنجیرهٔ روزهای فعال، نشان‌ها و آخرین رویدادها (§8.4/§8.6/§8.7)."""
    return await student_plan.xp_summary(db, current.id)
