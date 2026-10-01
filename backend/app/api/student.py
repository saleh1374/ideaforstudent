"""Student panel APIs (student spec §7, §3.3, §5, §6, §4.3)."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthUser, get_current_user
from app.core.config import get_settings
from app.core.db import get_db
from sqlalchemy.orm import selectinload

from app.models.assessment import AttemptAnswer, Exam, ExamAttempt, ExamItem
from app.models.catalog import Book, Chapter, Period, Topic
from app.models.org import StudentProfile
from app.models.slm import ErrorRecord, PlanTask, StudentTopicState
from app.services.assessment import submit_attempt

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

    # پیشرفت در برنامه (MVP: نسبت کارهای انجام‌شده امروز/دوره)
    tasks = (
        await db.execute(select(PlanTask).where(PlanTask.student_user_id == current.id))
    ).scalars().all()
    done = sum(1 for t in tasks if t.status == "done")
    progress_pct = round(100.0 * done / len(tasks), 1) if tasks else 0.0

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
    attempt = ExamAttempt(exam_id=exam.id, student_user_id=current.id, status="in_progress")
    db.add(attempt)
    await db.commit()
    await db.refresh(attempt)
    return {
        "attempt_id": attempt.id,
        "items": [
            {
                "exam_item_id": ei.id,
                "order": ei.order,
                "body": ei.item.body,
                "options": ei.item.options,
                "points": ei.points,
            }
            for ei in exam.exam_items
        ],
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

    result = await submit_attempt(db, exam=exam, attempt=attempt, answers=[a.model_dump() for a in body.answers])
    await db.commit()
    return result


@router.get("/errors")
async def error_notebook(current: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """دفترچه خطا (§6)."""
    rows = (
        await db.execute(select(ErrorRecord).where(ErrorRecord.student_user_id == current.id).order_by(ErrorRecord.created_at.desc()))
    ).scalars().all()
    by_cause: dict[str, int] = {}
    for r in rows:
        by_cause[r.cause] = by_cause.get(r.cause, 0) + 1
    return {
        "errors": [
            {
                "id": r.id,
                "topic_id": r.topic_id,
                "cause": r.cause,
                "status": r.status,
                "item": r.item_snapshot,
                "created_at": r.created_at,
            }
            for r in rows
        ],
        "by_cause": by_cause,
    }


@router.get("/tasks")
async def my_tasks(current: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
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
            }
            for t in rows
        ]
    }


class TaskDoneIn(BaseModel):
    minicheck_passed: bool = False


@router.post("/tasks/{task_id}/complete")
async def complete_task(task_id: int, body: TaskDoneIn, current: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    task = await db.get(PlanTask, task_id)
    if task is None or task.student_user_id != current.id:
        raise HTTPException(404, "کار یافت نشد")
    # «مطالعه شد» فقط با گذراندن آزمونک (§4.3)
    if task.task_type == "lesson" and not body.minicheck_passed:
        raise HTTPException(400, "برای تیک درس باید آزمونک را بگذرانید")
    task.status = "done"
    task.minicheck_passed = 1 if body.minicheck_passed else 0
    await db.commit()
    return {"ok": True}
