"""Province / ministry aggregations (roadmap phase 7 «مدیر استان/وزارت»).

تجمیع سطح مبحث برای استان و کشور در جدول ذخیره‌شده national_topic_stats؛
قاعده حریم خصوصی (حداقل جمعیت ۱۰) هنگام محاسبه اعمال می‌شود — زیر حد
نصاب، ردیف با is_suppressed=1 ذخیره می‌شود و عدد خالی برمی‌گردد."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.catalog import Chapter, Topic
from app.models.org import School, StudentProfile
from app.models.slm import StudentTopicState
from app.models.stats import NationalTopicStat


async def _topic_students(db: AsyncSession, province_id: int | None) -> dict[int, list[StudentTopicState]]:
    """مبحث ← شواهد دانش‌آموزان (استان یا کل کشور)."""
    schools = (await db.execute(select(School))).scalars().all()
    school_ids = [sc.id for sc in schools]
    if province_id is not None:
        school_ids = [sc.id for sc in schools if sc.province_id == province_id]
    if not school_ids:
        return {}
    profiles = (
        await db.execute(select(StudentProfile).where(StudentProfile.school_id.in_(school_ids)))
    ).scalars().all()
    user_ids = [p.user_id for p in profiles]
    if not user_ids:
        return {}
    states = (
        await db.execute(select(StudentTopicState).where(StudentTopicState.student_user_id.in_(user_ids)))
    ).scalars().all()
    by_topic: dict[int, list[StudentTopicState]] = {}
    for st in states:
        by_topic.setdefault(st.topic_id, []).append(st)
    return by_topic


async def recompute_topic_stats(db: AsyncSession, province_id: int | None = None) -> dict:
    """بازمحاسبه و ذخیره تجمیع‌ها (national یا یک استان)."""
    s = get_settings()
    scope = "national" if province_id is None else "province"
    pid = 0 if province_id is None else province_id

    by_topic = await _topic_students(db, province_id)
    topics = {t.id: t for t in (await db.execute(select(Topic))).scalars()}
    chapters = {c.id: c for c in (await db.execute(select(Chapter))).scalars()}

    # ردیف‌های قبلی همین دامنه حذف و بازسازی می‌شوند
    old = (
        await db.execute(
            select(NationalTopicStat).where(
                NationalTopicStat.scope == scope, NationalTopicStat.province_id == pid
            )
        )
    ).scalars().all()
    for row in old:
        await db.delete(row)
    await db.flush()

    written = 0
    suppressed = 0
    for topic_id, states in by_topic.items():
        topic = topics.get(topic_id)
        if topic is None:
            continue
        chapter = chapters.get(topic.chapter_id)
        subject = None
        if chapter is not None:
            from app.models.catalog import Book

            book = await db.get(Book, chapter.book_id)
            subject = book.subject if book else None
        students = {st.student_user_id for st in states if st.evidence_count >= s.evidence_min_for_status}
        is_suppressed = len(students) < s.min_group_size
        with_data = [st for st in states if st.evidence_count >= s.evidence_min_for_status]
        if is_suppressed:
            suppressed += 1
            avg_m = avg_r = weak = None
        else:
            avg_m = round(sum(st.effective_mastery for st in with_data) / len(with_data), 1) if with_data else None
            avg_r = round(sum(st.retention for st in with_data) / len(with_data), 3) if with_data else None
            weak = (
                round(sum(1 for st in with_data if st.effective_mastery < s.threshold_consolidating) / len(with_data), 3)
                if with_data
                else None
            )
        db.add(
            NationalTopicStat(
                scope=scope,
                province_id=pid,
                topic_id=topic_id,
                subject=subject,
                students_count=len(students),
                avg_mastery=avg_m,
                avg_retention=avg_r,
                weak_ratio=weak,
                is_suppressed=1 if is_suppressed else 0,
                updated_at=datetime.now(timezone.utc),
            )
        )
        written += 1
    await db.flush()
    return {"scope": scope, "written": written, "suppressed": suppressed, "min_group": s.min_group_size}


async def topic_stats(db: AsyncSession, province_id: int | None = None) -> dict:
    """خواندن تجمیع‌ها (اگر خالی بود، اول بازمحاسبه کن)."""
    scope = "national" if province_id is None else "province"
    pid = 0 if province_id is None else province_id
    rows = (
        await db.execute(
            select(NationalTopicStat)
            .where(NationalTopicStat.scope == scope, NationalTopicStat.province_id == pid)
            .order_by(NationalTopicStat.avg_mastery.asc().nulls_last())
        )
    ).scalars().all()
    if not rows:
        await recompute_topic_stats(db, province_id)
        rows = (
            await db.execute(
                select(NationalTopicStat)
                .where(NationalTopicStat.scope == scope, NationalTopicStat.province_id == pid)
                .order_by(NationalTopicStat.avg_mastery.asc().nulls_last())
            )
        ).scalars().all()
    return {
        "scope": scope,
        "province_id": province_id,
        "rows": [
            {
                "topic_id": r.topic_id,
                "subject": r.subject,
                "students_count": r.students_count,
                "avg_mastery": r.avg_mastery,
                "avg_retention": r.avg_retention,
                "weak_ratio": r.weak_ratio,
                "suppressed": bool(r.is_suppressed),
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ],
    }


async def overview(db: AsyncSession, province_id: int | None = None) -> dict:
    """نمای کلان استان/کشور: مدارس، دانش‌آموزان، میانگین تسلط، بدترین مباحث."""
    s = get_settings()
    schools = (await db.execute(select(School))).scalars().all()
    if province_id is not None:
        schools = [sc for sc in schools if sc.province_id == province_id]
    school_ids = [sc.id for sc in schools]
    profiles = (
        await db.execute(select(StudentProfile).where(StudentProfile.school_id.in_(school_ids)))
    ).scalars() if school_ids else []
    user_ids = [p.user_id for p in profiles]

    states = (
        await db.execute(select(StudentTopicState).where(StudentTopicState.student_user_id.in_(user_ids)))
    ).scalars() if user_ids else []
    with_data = [st for st in states if st.evidence_count >= s.evidence_min_for_status]
    students = {st.student_user_id for st in with_data}

    avg_mastery = (
        round(sum(st.effective_mastery for st in with_data) / len(with_data), 1) if with_data else None
    )
    suppressed = len(students) < s.min_group_size

    stats = await topic_stats(db, province_id)
    visible = [r for r in stats["rows"] if not r["suppressed"] and r["avg_mastery"] is not None]
    worst = visible[:5]

    return {
        "scope": "national" if province_id is None else "province",
        "province_id": province_id,
        "schools_count": len(schools),
        "students_count": len(students),
        "avg_mastery": None if suppressed else avg_mastery,
        "suppressed": suppressed,
        "min_group": s.min_group_size,
        "worst_topics": worst,
        "note_fa": (
            f"اعداد سطح بالا فقط با حداقل {s.min_group_size} دانش‌آموز دارای داده نمایش داده می‌شوند."
        ),
    }
