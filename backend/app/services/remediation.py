"""Targeted assessment + remediation/retest workflow (roadmap phase 4
«آزمون هدف‌محور + گردش کار ترمیم/بازآزمون»).

چرخه: خطا باز → ساخت بازآزمون ترمیمی از همان مباحث → خطا «در حال ترمیم»
→ بازآزمون: پاسخ درست ⇒ رفع خطا؛ پاسخ نادرست ⇒ بازگشت خطا (relapse).
همه آستانه‌ها از Settings می‌آیند (قابل کالیبراسیون پایلوت)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.assessment import AttemptAnswer, Exam, ExamAttempt, ExamItem, QuestionItem
from app.models.catalog import Book, Chapter, Topic
from app.models.org import StudentProfile
from app.models.slm import ErrorRecord, PlanTask


async def weak_topics_with_open_errors(db: AsyncSession, student_user_id: int) -> list[dict]:
    """مباحثی که خطای باز/در ترمیم دارند + تعداد هر علت — ورودی ساخت بازآزمون."""
    errors = (
        await db.execute(
            select(ErrorRecord).where(
                ErrorRecord.student_user_id == student_user_id,
                ErrorRecord.status.in_(["open", "in_remediation", "relapsed"]),
            )
        )
    ).scalars().all()
    by_topic: dict[int, dict] = {}
    for e in errors:
        row = by_topic.setdefault(e.topic_id, {"topic_id": e.topic_id, "causes": {}, "error_ids": []})
        row["causes"][e.cause] = row["causes"].get(e.cause, 0) + 1
        row["error_ids"].append(e.id)
    if not by_topic:
        return []
    topics = {
        t.id: t
        for t in (await db.execute(select(Topic).where(Topic.id.in_(by_topic.keys())))).scalars()
    }
    out = []
    for tid, row in by_topic.items():
        t = topics.get(tid)
        if t is None:
            continue
        out.append({**row, "title": t.title_fa})
    out.sort(key=lambda r: -sum(r["causes"].values()))
    return out


async def build_retest_exam(db: AsyncSession, student_user_id: int) -> dict:
    """ساخت بازآزمون ترمیمی هدف‌محور از مباحث دارای خطای باز (phase 4).
    خطاها → in_remediation؛ یک PlanTask نوع retest هم ساخته می‌شود."""
    s = get_settings()
    targets = await weak_topics_with_open_errors(db, student_user_id)
    if not targets:
        return {"ok": False, "reason": "خطای بازی برای ترمیم ندارید"}

    profile = (
        await db.execute(select(StudentProfile).where(StudentProfile.user_id == student_user_id))
    ).scalar_one_or_none()
    if profile is None:
        return {"ok": False, "reason": "پروفایل دانش‌آموز یافت نشد"}

    # سؤالات هر مبحث (حداکثر retest_items_per_topic)
    exam_items: list[QuestionItem] = []
    covered: list[int] = []
    for t in targets[:5]:  # حداکثر ۵ مبحث در هر بازآزمون
        items = (
            await db.execute(
                select(QuestionItem)
                .where(QuestionItem.topic_id == t["topic_id"], QuestionItem.is_active == 1)
                .limit(s.retest_items_per_topic)
            )
        ).scalars().all()
        if items:
            exam_items.extend(items)
            covered.append(t["topic_id"])

    if not exam_items:
        return {"ok": False, "reason": "برای این مباحث سؤال فعالی وجود ندارد"}

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # درس مبحث از روی کتاب (کپیتال → فصل → مبحث)
    subject = "math"
    first = await db.get(Topic, covered[0])
    if first is not None:
        chapter = await db.get(Chapter, first.chapter_id)
        book = await db.get(Book, chapter.book_id) if chapter else None
        if book is not None:
            subject = book.subject

    exam = Exam(
        title_fa="بازآزمون ترمیمی — " + "، ".join(next(t["title"] for t in targets if t["topic_id"] == tid) for tid in covered[:3]),
        exam_type="remedial_retest",
        grade=profile.grade,
        subject=subject,
        scope="student",
        school_id=profile.school_id,
        class_id=profile.class_id,
        status="published",
        opens_at=now,
        closes_at=now + timedelta(days=s.retest_close_days),
        negative_marking_k=0.0,
        created_by=None,
    )
    db.add(exam)
    await db.flush()
    for i, q in enumerate(exam_items, start=1):
        db.add(ExamItem(exam_id=exam.id, item_id=q.id, order=i, points=1.0))

    # خطاها → در حال ترمیم
    error_ids = [eid for t in targets if t["topic_id"] in covered for eid in t["error_ids"]]
    if error_ids:
        errs = (
            await db.execute(select(ErrorRecord).where(ErrorRecord.id.in_(error_ids)))
        ).scalars().all()
        for e in errs:
            if e.status != "in_remediation":
                e.status = "in_remediation"

    db.add(
        PlanTask(
            student_user_id=student_user_id,
            topic_id=covered[0],
            task_type="retest",
            payload={"exam_id": exam.id, "topic_ids": covered},
            for_date=datetime.now(timezone.utc).date(),
            priority=2.0,
            status="pending",
        )
    )
    await db.flush()
    return {"ok": True, "exam_id": exam.id, "topics": covered, "item_count": len(exam_items)}


async def apply_retest_result(
    db: AsyncSession, *, student_user_id: int, attempt: ExamAttempt, answers: list[AttemptAnswer]
) -> dict:
    """پس از نمره‌دهی بازآزمون: پاسخ درست هر مبحث ⇒ رفع خطاها؛ نادرست ⇒ بازگشت."""
    s = get_settings()
    # نگاشت مبحث ← درستی از پاسخ‌های همین تلاش
    exam_items = {
        ei.id: ei
        for ei in (await db.execute(select(ExamItem).where(ExamItem.exam_id == attempt.exam_id))).scalars()
    }
    topic_correct: dict[int, list[bool]] = {}
    for a in answers:
        ei = exam_items.get(a.exam_item_id)
        if ei is None:
            continue
        q = await db.get(QuestionItem, ei.item_id)
        if q is None:
            continue
        topic_correct.setdefault(q.topic_id, []).append(bool(a.is_correct))

    resolved = 0
    relapsed = 0
    for topic_id, results in topic_correct.items():
        ratio = sum(results) / len(results)
        errs = (
            await db.execute(
                select(ErrorRecord).where(
                    ErrorRecord.student_user_id == student_user_id,
                    ErrorRecord.topic_id == topic_id,
                    # فقط خطاهایی که build_retest_exam وارد چرخه کرده؛
                    # خطاهای تازهٔ همین تلاش open می‌مانند
                    ErrorRecord.status == "in_remediation",
                )
            )
        ).scalars().all()
        now = datetime.now(timezone.utc)
        for e in errs:
            if ratio >= s.retest_pass_ratio:
                e.status = "resolved"
                e.resolved_at = now
                resolved += 1
            else:
                e.status = "relapsed"
                e.relapsed_at = now
                relapsed += 1

    # کار برنامه مرتبط را ببند
    tasks = (
        await db.execute(
            select(PlanTask).where(
                PlanTask.student_user_id == student_user_id,
                PlanTask.task_type == "retest",
                PlanTask.status == "pending",
            )
        )
    ).scalars().all()
    for t in tasks:
        if t.payload.get("exam_id") == attempt.exam_id:
            t.status = "done"

    return {"resolved": resolved, "relapsed": relapsed}
