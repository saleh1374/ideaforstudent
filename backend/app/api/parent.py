"""Parent panel APIs (roadmap phase 5، سند پنل والدین §17).

والد فقط فرزندان متصل‌شده (ParentLink) را می‌بیند؛ داده تجمیعی و بدون
مقایسه با دانش‌آموزان دیگر — اصل حفظ حریم خصوصی کودک."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthUser, get_current_user
from app.core.config import get_settings
from app.core.db import get_db
from app.models.catalog import Topic
from app.models.org import ParentLink, StudentProfile, User
from app.models.slm import ErrorRecord, PlanTask, StudentTopicState
from app.services.slm import status_of

router = APIRouter(prefix="/parent", tags=["parent"])


async def _my_children(db: AsyncSession, parent_id: int) -> list[User]:
    links = (
        await db.execute(
            select(ParentLink).where(
                ParentLink.parent_user_id == parent_id, ParentLink.status == "active"
            )
        )
    ).scalars().all()
    if not links:
        return []
    ids = [l.student_user_id for l in links]
    return list((await db.execute(select(User).where(User.id.in_(ids)))).scalars())


@router.get("/children")
async def children(current: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    users = await _my_children(db, current.id)
    out = []
    for u in users:
        profile = (
            await db.execute(select(StudentProfile).where(StudentProfile.user_id == u.id))
        ).scalar_one_or_none()
        out.append(
            {
                "id": u.id,
                "full_name": u.full_name,
                "grade": profile.grade if profile else None,
                "class_id": profile.class_id if profile else None,
            }
        )
    return {"children": out}


@router.get("/children/{student_id}/overview")
async def child_overview(
    student_id: int,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """نمای کلان فرزند: دو شاخص جدا (پیشرفت ≠ تسلط) + وضعیت مباحث + خطاهای باز.
    بدون رتبه و بدون مقایسه با هم‌کلاسی‌ها (سند والدین)."""
    link = (
        await db.execute(
            select(ParentLink).where(
                ParentLink.parent_user_id == current.id,
                ParentLink.student_user_id == student_id,
                ParentLink.status == "active",
            )
        )
    ).scalar_one_or_none()
    if link is None:
        raise HTTPException(403, "این دانش‌آموز به شما متصل نیست")

    states = (
        await db.execute(select(StudentTopicState).where(StudentTopicState.student_user_id == student_id))
    ).scalars().all()
    topics = {t.id: t for t in (await db.execute(select(Topic))).scalars()}

    num = den = 0.0
    for st in states:
        t = topics.get(st.topic_id)
        w = (t.blueprint_weight if t else 1.0) or 1.0
        num += w * st.effective_mastery
        den += w
    mastery_pct = round(num / den, 1) if den else 0.0

    tasks = (
        await db.execute(select(PlanTask).where(PlanTask.student_user_id == student_id))
    ).scalars().all()
    done = sum(1 for t in tasks if t.status == "done")
    progress_pct = round(100.0 * done / len(tasks), 1) if tasks else 0.0

    errors = (
        await db.execute(select(ErrorRecord).where(ErrorRecord.student_user_id == student_id))
    ).scalars().all()
    # حل‌نشده = باز یا در چرخه ترمیم یا بازگشته
    open_errors = [e for e in errors if e.status in ("open", "in_remediation", "relapsed")]

    s = get_settings()
    status_counts = {"mastered": 0, "consolidating": 0, "weak": 0, "critical": 0, "unknown": 0}
    weak_topics = []
    for st in states:
        k = status_of(st.effective_mastery, st.evidence_count)
        status_counts[k] = status_counts.get(k, 0) + 1
        if k in ("weak", "critical") and len(weak_topics) < 5 and st.topic_id in topics:
            weak_topics.append({"topic_id": st.topic_id, "title": topics[st.topic_id].title_fa, "status": k})

    gap = round(progress_pct - mastery_pct, 1)
    advice = None
    if abs(gap) >= 15 and gap > 0:
        advice = "خوانده ولی جا نیفتاده — مرور فاصله‌دار و بسته ترمیمی اولویت دارد."
    elif abs(gap) >= 15 and gap < 0:
        advice = "تسلط بالاست ولی عقب‌ماندگی برنامه داریم — سرعت پیشروی بررسی شود."
    elif open_errors:
        advice = f"{len(open_errors)} خطای باز دارد؛ بازآزمون ترمیمی پیشنهاد می‌شود."

    return {
        "student_id": student_id,
        "progress_pct": progress_pct,
        "mastery_pct": mastery_pct,
        "gap": gap,
        "gap_message": advice,
        "errors_total": len(errors),
        "errors_open": len(open_errors),
        "status_counts": status_counts,
        "weak_topics": weak_topics,
        "note_fa": "مقایسه با دانش‌آموزان دیگر نمایش داده نمی‌شود؛ این نمای انحصاری فرزند شماست.",
    }
