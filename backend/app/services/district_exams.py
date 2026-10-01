"""سرویس آزمون‌های رسمی ناحیه، تحلیل سؤال، مداخله و مأموریت
(district spec §20–§21, §25–§27).

نکات طراحی:
- آزمون رسمی ناحیه روی جدول موجود `exams` (scope='district') سوار می‌شود تا
  جریان موجود دانش‌آموز (start/submit)، تصحیح، شواهد SLM و دفترچه خطا
  دوباره‌کاری نشود — نتایج و تحلیل سؤال از همان AttemptAnswer خوانده می‌شود.
- همه تجمیج‌ها قاعده حداقل جمعیت (`Settings.min_group_size`) را رعایت می
  کنند؛ زیر حد نصاب هیچ عددی برنمی‌گردد (suppressed=True).
- آستانه‌های نو در `DistrictExamSettings` محلی تعریف می‌شوند چون
  `app/core/config.py` فایل مشترک است و نباید ویرایش شود (parallel-safe).
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

from fastapi import HTTPException
from pydantic_settings import BaseSettings
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.models.assessment import AttemptAnswer, Exam, ExamAttempt, ExamItem, QuestionItem
from app.models.catalog import Book, Chapter, Topic
from app.models.district_exams import (
    DistrictExam,
    DistrictExamSchool,
    DistrictIntervention,
    DistrictInterventionSchool,
    DistrictMission,
    DistrictMissionSchool,
)
from app.models.org import ClassRoom, School, StudentProfile, User
from app.models.slm import StudentTopicState
from app.services.rbac_service import log_action
from app.services.slm import status_of


class DistrictExamSettings(BaseSettings):
    """آستانه‌های قابل تنظیمِ آزمون/مداخله/مأموریت ناحیه — مثل سند اصلی
    «مقدارهای عددی فقط فرض هستند و باید قابل تنظیم باشند»؛ از env خوانده
    می‌شوند (بدون پیشوند، مانند Settings اصلی)."""

    district_exam_pass_percent: float = 60.0    # حداقل قبولی در آزمون رسمی (٪)
    district_exam_default_items: int = 10       # تعداد پیش‌فرض نمونه از بانک سؤال
    item_review_discrimination: float = 0.15    # §21: زیر این قدرت تفکیک → نیازمند بازبینی
    item_review_gap: float = 0.30               # §21: |تجربی − پیشینی| بیش از این → بازبینی
    item_min_responses: int = 3                 # کمتر از این پاسخ، تحلیل قطعی نیست
    intervention_default_days: int = 14         # مدت پیش‌فرض مداخله (§25: ۲ هفته)
    intervention_retention_days: int = 21       # سنجش ماندگاری ~۳ هفته پس از بازآزمون (§26)
    intervention_min_gain: float = 5.0          # حداقل رشد برای «اثر داشته» (٪)
    mission_default_days: int = 14              # مهلت پیش‌فرض مأموریت (§27: ~۲ هفته)

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_district_exam_settings() -> DistrictExamSettings:
    return DistrictExamSettings()


# دشواری پیش‌بانک‌شده هر برچسب difficulty — مبنای «دشواری پیشینی» برای مقایسه
# با دشواری تجربی در §21 (p پاسخ درست انتظاری).
PRIOR_P_BY_DIFFICULTY = {"easy": 0.85, "medium": 0.65, "hard": 0.45}

INTERVENTION_TYPES = ("course", "supervision", "replacement", "program")
INTERVENTION_TYPE_FA = {
    "course": "دوره آموزشی",
    "supervision": "نظارت",
    "replacement": "تعویض",
    "program": "برنامه آموزشی",
}

EXAM_STATUS_FA = {
    "draft": "پیش‌نویس",
    "published": "منتشرشده",
    "graded": "تصحیح‌شده",
    "closed": "بسته‌شده",
}

# گذارهای مجاز وضعیت آزمون رسمی: draft → published → graded → closed
# (بازگشت published→draft فقط پیش از ثبت هر پاسخ، برای اصلاح پیش از انتشار)
EXAM_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"published"},
    "published": {"graded", "draft"},
    "graded": {"closed"},
    "closed": set(),
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ------------------------- ابزارهای عمومی -------------------------


async def district_exam_or_404(db: AsyncSession, exam_id: int, district_id: int) -> DistrictExam:
    exam = await db.get(DistrictExam, exam_id)
    if exam is None or exam.district_id != district_id:
        raise HTTPException(404, "آزمون رسمی ناحیه یافت نشد")
    return exam


async def _district_schools_map(db: AsyncSession, school_ids: list[int], district_id: int) -> dict[int, School]:
    """اعتبارسنجی مدارس انتخابی: همه باید در همین ناحیه باشند (§33)."""
    unique = list(dict.fromkeys(school_ids))
    if not unique:
        raise HTTPException(400, "دست‌کم یک مدرسه انتخاب کنید")
    rows = (
        await db.execute(
            select(School).where(School.id.in_(unique), School.district_id == district_id)
        )
    ).scalars().all()
    found = {sc.id: sc for sc in rows}
    missing = [sid for sid in unique if sid not in found]
    if missing:
        raise HTTPException(400, f"مدرسه‌ای خارج از این ناحیه یا ناموجود: {', '.join(map(str, missing))}")
    return found


def _round1(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


# ------------------------- §20 آزمون رسمی ناحیه -------------------------


async def sample_bank_items(
    db: AsyncSession, grade: str, subject: str, limit: int | None = None
) -> list[QuestionItem]:
    """نمونه‌برداری از بانک سؤال موجود برای (پایه، درس) — QuestionItem ←
    Topic ← Chapter ← Book."""
    ds = get_district_exam_settings()
    q = (
        select(QuestionItem)
        .join(Topic, Topic.id == QuestionItem.topic_id)
        .join(Chapter, Chapter.id == Topic.chapter_id)
        .join(Book, Book.id == Chapter.book_id)
        .where(Book.grade == grade, Book.subject == subject, QuestionItem.is_active == 1)
        .order_by(QuestionItem.id)
    )
    if limit:
        q = q.limit(limit)
    else:
        q = q.limit(ds.district_exam_default_items)
    return list((await db.execute(q)).scalars())


async def create_district_exam(
    db: AsyncSession,
    *,
    district_id: int,
    created_by: int,
    title_fa: str,
    grade: str,
    subject: str,
    school_ids: list[int],
    blueprint: str | None = None,
    opens_at: datetime | None = None,
    closes_at: datetime | None = None,
    item_ids: list[int] | None = None,
    item_count: int | None = None,
) -> DistrictExam:
    """ساخت آزمون رسمی ناحیه در وضعیت draft: مدارس انتخابی + اقلام سؤال
    (explicit item_ids یا نمونه خودکار از بانک برای همان پایه/درس)."""
    if not title_fa.strip():
        raise HTTPException(400, "عنوان آزمون الزامی است")
    if not grade.strip() or not subject.strip():
        raise HTTPException(400, "پایه و درس الزامی است")
    if opens_at is not None and closes_at is not None and opens_at >= closes_at:
        raise HTTPException(400, "زمان پایان باید پس از زمان شروع باشد")

    schools_map = await _district_schools_map(db, school_ids, district_id)

    # اقلام سؤال: صریح یا نمونه از بانک
    if item_ids is not None:
        unique_items = list(dict.fromkeys(item_ids))
        if not unique_items:
            raise HTTPException(400, "فهرست سؤالات نمی‌تواند خالی باشد")
        items = list(
            (
                await db.execute(
                    select(QuestionItem).where(
                        QuestionItem.id.in_(unique_items), QuestionItem.is_active == 1
                    )
                )
            ).scalars()
        )
        if len(items) != len(unique_items):
            raise HTTPException(400, "یکی از شناسه سؤالات نامعتبر یا غیرفعال است")
        items.sort(key=lambda it: unique_items.index(it.id))
    else:
        items = await sample_bank_items(db, grade, subject, limit=item_count)
        if not items:
            raise HTTPException(
                400,
                "بانک سؤال برای این پایه/درس سؤالی ندارد؛ item_ids مشخص کنید",
            )

    # آزمون پیوندی موجود (scope=district) — دانش‌آموزان از همان جریان موجود
    # پاسخ می‌دهند؛ exam_type=period_exam تا شاهد SLM با وزن آزمون رسمی ثبت شود.
    backing = Exam(
        title_fa=title_fa.strip(),
        exam_type="period_exam",
        grade=grade,
        subject=subject,
        scope="district",
        blueprint=None,
        status="draft",
        opens_at=opens_at,
        closes_at=closes_at,
        created_by=created_by,
    )
    db.add(backing)
    await db.flush()

    exam = DistrictExam(
        district_id=district_id,
        exam_id=backing.id,
        title_fa=title_fa.strip(),
        grade=grade,
        subject=subject,
        blueprint=blueprint.strip() if blueprint and blueprint.strip() else None,
        status="draft",
        opens_at=opens_at,
        closes_at=closes_at,
        created_by=created_by,
    )
    db.add(exam)
    await db.flush()

    for sid in schools_map:
        db.add(DistrictExamSchool(exam_id=exam.id, school_id=sid))
    for i, item in enumerate(items, start=1):
        db.add(ExamItem(exam_id=backing.id, item_id=item.id, order=i, points=1.0))
    await db.flush()

    await log_action(
        db,
        actor_user_id=created_by,
        action="district_exam_created",
        entity_type="district_exam",
        entity_id=exam.id,
        detail=(
            f"district={district_id} grade={grade} subject={subject} "
            f"schools={len(schools_map)} items={len(items)}"
        ),
    )
    await db.flush()
    return exam


async def list_district_exams(db: AsyncSession, district_id: int, status: str | None = None) -> list[dict]:
    q = select(DistrictExam).where(DistrictExam.district_id == district_id).order_by(DistrictExam.id.desc())
    exams = list((await db.execute(q)).scalars())
    if status is not None:
        exams = [e for e in exams if e.status == status]
    if not exams:
        return []

    exam_ids = [e.id for e in exams]
    backing_ids = [e.exam_id for e in exams if e.exam_id is not None]

    school_counts: dict[int, int] = {}
    for eid, cnt in (
        await db.execute(
            select(DistrictExamSchool.exam_id, DistrictExamSchool.id).where(
                DistrictExamSchool.exam_id.in_(exam_ids)
            )
        )
    ).all():
        school_counts[eid] = school_counts.get(eid, 0) + 1

    item_counts: dict[int, int] = {}
    if backing_ids:
        for eid, cnt in (
            await db.execute(
                select(ExamItem.exam_id, ExamItem.id).where(ExamItem.exam_id.in_(backing_ids))
            )
        ).all():
            item_counts[eid] = item_counts.get(eid, 0) + 1

    participants: dict[int, set[int]] = {}
    if backing_ids:
        for eid, sid in (
            await db.execute(
                select(ExamAttempt.exam_id, ExamAttempt.student_user_id).where(
                    ExamAttempt.exam_id.in_(backing_ids), ExamAttempt.status == "graded"
                )
            )
        ).all():
            participants.setdefault(eid, set()).add(sid)

    creator_names = await _user_names(db, {e.created_by for e in exams if e.created_by is not None})

    rows = []
    for e in exams:
        rows.append(
            {
                **exam_row(e),
                "schools_count": school_counts.get(e.id, 0),
                "items_count": item_counts.get(e.exam_id or -1, 0),
                "participants": len(participants.get(e.exam_id or -1, set())),
                "created_by_name": creator_names.get(e.created_by) if e.created_by else None,
            }
        )
    return rows


def exam_row(exam: DistrictExam) -> dict:
    return {
        "id": exam.id,
        "exam_id": exam.exam_id,
        "district_id": exam.district_id,
        "title_fa": exam.title_fa,
        "grade": exam.grade,
        "subject": exam.subject,
        "blueprint": exam.blueprint,
        "status": exam.status,
        "status_fa": EXAM_STATUS_FA.get(exam.status, exam.status),
        "opens_at": exam.opens_at,
        "closes_at": exam.closes_at,
        "created_by": exam.created_by,
        "created_at": exam.created_at,
        "next_statuses": sorted(EXAM_TRANSITIONS.get(exam.status, set())),
    }


async def _user_names(db: AsyncSession, user_ids: set[int]) -> dict[int, str]:
    if not user_ids:
        return {}
    rows = (await db.execute(select(User.id, User.full_name).where(User.id.in_(user_ids)))).all()
    return {uid: name for uid, name in rows}


async def district_exam_detail(db: AsyncSession, exam: DistrictExam) -> dict:
    schools = list(
        (
            await db.execute(
                select(School)
                .join(DistrictExamSchool, DistrictExamSchool.school_id == School.id)
                .where(DistrictExamSchool.exam_id == exam.id)
                .order_by(School.id)
            )
        ).scalars()
    )
    items: list[dict] = []
    attempts_count = 0
    if exam.exam_id is not None:
        exam_items = list(
            (
                await db.execute(
                    select(ExamItem)
                    .options(selectinload(ExamItem.item).selectinload(QuestionItem.topic))
                    .where(ExamItem.exam_id == exam.exam_id)
                    .order_by(ExamItem.order)
                )
            ).scalars()
        )
        for ei in exam_items:
            item = ei.item
            items.append(
                {
                    "order": ei.order,
                    "item_id": item.id,
                    "body": item.body,
                    "difficulty": item.difficulty,
                    "topic": item.topic.title_fa if item.topic is not None else None,
                    "points": ei.points,
                }
            )
        attempts_count = len(
            (
                await db.execute(
                    select(ExamAttempt.id).where(
                        ExamAttempt.exam_id == exam.exam_id, ExamAttempt.status == "graded"
                    )
                )
            ).all()
        )
    creator_names = await _user_names(db, {exam.created_by} if exam.created_by else set())
    return {
        **exam_row(exam),
        "created_by_name": creator_names.get(exam.created_by) if exam.created_by else None,
        "schools": [{"id": sc.id, "name": sc.name, "school_code": sc.school_code} for sc in schools],
        "items": items,
        "participants": attempts_count,
    }


async def set_exam_status(
    db: AsyncSession, exam: DistrictExam, new_status: str, actor_id: int
) -> DistrictExam:
    """گذار وضعیت با ممیزی صریح — «کسی آزمون رسمی را منتشر کرد؟» (§20)."""
    if new_status == exam.status:
        return exam
    allowed = EXAM_TRANSITIONS.get(exam.status, set())
    if new_status not in allowed:
        raise HTTPException(
            400,
            f"گذار وضعیت «{EXAM_STATUS_FA.get(exam.status, exam.status)} → "
            f"{EXAM_STATUS_FA.get(new_status, new_status)}» مجاز نیست",
        )

    backing = await db.get(Exam, exam.exam_id) if exam.exam_id else None

    if new_status == "published":
        schools_count = (
            await db.execute(
                select(DistrictExamSchool.id).where(DistrictExamSchool.exam_id == exam.id)
            )
        ).all()
        items_count = (
            (
                await db.execute(
                    select(ExamItem.id).where(ExamItem.exam_id == exam.exam_id)
                )
            ).all()
            if exam.exam_id
            else []
        )
        if not schools_count:
            raise HTTPException(400, "برای انتشار، دست‌کم یک مدرسه لازم است")
        if not items_count:
            raise HTTPException(400, "برای انتشار، دست‌کم یک سؤال لازم است")
        exam.status = "published"
        if backing is not None:
            backing.status = "published"
        await log_action(
            db,
            actor_user_id=actor_id,
            action="district_exam_published",
            entity_type="district_exam",
            entity_id=exam.id,
            detail=(
                f"district={exam.district_id} backing_exam={exam.exam_id} "
                f"schools={len(schools_count)} items={len(items_count)}"
            ),
        )
    elif new_status == "draft":
        graded = (
            await db.execute(
                select(ExamAttempt.id).where(
                    ExamAttempt.exam_id == exam.exam_id, ExamAttempt.status == "graded"
                )
            )
        ).all() if exam.exam_id else []
        if graded:
            raise HTTPException(409, "پاسخی ثبت شده است؛ بازگشت به پیش‌نویس ممکن نیست")
        exam.status = "draft"
        if backing is not None:
            backing.status = "draft"
        await log_action(
            db,
            actor_user_id=actor_id,
            action="district_exam_unpublished",
            entity_type="district_exam",
            entity_id=exam.id,
            detail=f"district={exam.district_id}",
        )
    elif new_status == "graded":
        exam.status = "graded"
        if backing is not None:
            backing.status = "graded"
        await log_action(
            db,
            actor_user_id=actor_id,
            action="district_exam_graded",
            entity_type="district_exam",
            entity_id=exam.id,
            detail=f"district={exam.district_id}",
        )
    elif new_status == "closed":
        exam.status = "closed"
        if backing is not None:
            backing.status = "closed"
        await log_action(
            db,
            actor_user_id=actor_id,
            action="district_exam_closed",
            entity_type="district_exam",
            entity_id=exam.id,
            detail=f"district={exam.district_id}",
        )
    await db.flush()
    return exam


# ------------------------- نتایج آزمون (§20/§3 — با سرکوب گروه کوچک) -------------------------


async def _attempts_with_snapshot(db: AsyncSession, backing_exam_id: int) -> list[dict]:
    """تلاش‌های تصحیح‌شده + عکس سازمانی (مدرسه/کلاس) از روی پاسخ‌ها."""
    attempts = list(
        (
            await db.execute(
                select(ExamAttempt).where(
                    ExamAttempt.exam_id == backing_exam_id, ExamAttempt.status == "graded"
                )
            )
        ).scalars()
    )
    if not attempts:
        return []
    answers = list(
        (
            await db.execute(
                select(AttemptAnswer)
                .join(ExamAttempt, ExamAttempt.id == AttemptAnswer.attempt_id)
                .where(ExamAttempt.exam_id == backing_exam_id)
            )
        ).scalars()
    )
    first_by_attempt: dict[int, AttemptAnswer] = {}
    for ans in answers:
        first_by_attempt.setdefault(ans.attempt_id, ans)
    out = []
    for at in attempts:
        snap = first_by_attempt.get(at.id)
        out.append(
            {
                "attempt_id": at.id,
                "student_user_id": at.student_user_id,
                "percent": at.percent or 0.0,
                "school_id": snap.school_id if snap else None,
                "class_id": snap.class_id if snap else None,
            }
        )
    return out


def _aggregate(rows: list[dict], min_group: int, pass_percent: float) -> dict:
    """تجمیع یک گروه با قاعده حداقل جمعیت: زیر نصاب هیچ عددی برنمی‌گردد."""
    n = len(rows)
    suppressed = n < min_group
    avg = sum(r["percent"] for r in rows) / n if n else None
    passed = sum(1 for r in rows if r["percent"] >= pass_percent)
    return {
        "participants": n,
        "avg_percent": None if suppressed else _round1(avg),
        "pass_rate": None if suppressed else (round(100.0 * passed / n, 1) if n else None),
        "suppressed": suppressed,
        "min_group": min_group,
    }


async def exam_results(db: AsyncSession, exam: DistrictExam) -> dict:
    """نتایج به تفکیک مدرسه/کلاس با سرکوب گروه کوچک (§20 — مقایسه منصفانه
    Student → Class → School → District)."""
    s = get_settings()
    ds = get_district_exam_settings()
    if exam.exam_id is None or exam.status == "draft":
        return {
            "exam": exam_row(exam),
            "overall": None,
            "schools": [],
            "classes": [],
            "note_fa": "آزمون هنوز منتشر نشده است؛ نتایج پس از انتشار محاسبه می‌شود.",
        }

    assigned = list(
        (
            await db.execute(
                select(DistrictExamSchool.school_id).where(DistrictExamSchool.exam_id == exam.id)
            )
        ).all()
    )
    assigned_ids = {row[0] for row in assigned}

    attempts = await _attempts_with_snapshot(db, exam.exam_id)
    inside = [a for a in attempts if a["school_id"] in assigned_ids]
    outside_count = len(attempts) - len(inside)

    # مخاطبان: دانش‌آموزان مدارس انتخابی با همان پایه
    profiles = list(
        (
            await db.execute(
                select(StudentProfile).where(
                    StudentProfile.school_id.in_(assigned_ids),
                    StudentProfile.grade == exam.grade,
                )
            )
        ).scalars()
    )
    eligible_by_school: dict[int, int] = {}
    for p in profiles:
        eligible_by_school[p.school_id] = eligible_by_school.get(p.school_id, 0) + 1
    eligible_total = len(profiles)

    # تجمیع مدرسه‌ای
    schools_meta = {
        sc.id: sc
        for sc in (
            await db.execute(select(School).where(School.id.in_(assigned_ids)))
        ).scalars()
    }
    by_school: dict[int, list[dict]] = {sid: [] for sid in assigned_ids}
    for a in inside:
        by_school.setdefault(a["school_id"], []).append(a)

    school_rows = []
    for sid in sorted(by_school):
        agg = _aggregate(by_school[sid], s.min_group_size, ds.district_exam_pass_percent)
        school_rows.append(
            {
                "school_id": sid,
                "name": schools_meta[sid].name if sid in schools_meta else None,
                "eligible": eligible_by_school.get(sid, 0),
                **agg,
            }
        )

    # تجمیع کلاسی
    class_ids = {a["class_id"] for a in inside if a["class_id"] is not None}
    class_meta = {
        cr.id: cr
        for cr in (await db.execute(select(ClassRoom).where(ClassRoom.id.in_(class_ids)))).scalars()
    } if class_ids else {}
    by_class: dict[int, list[dict]] = {}
    for a in inside:
        if a["class_id"] is not None:
            by_class.setdefault(a["class_id"], []).append(a)
    class_rows = []
    for cid in sorted(by_class):
        agg = _aggregate(by_class[cid], s.min_group_size, ds.district_exam_pass_percent)
        meta = class_meta.get(cid)
        class_rows.append(
            {
                "class_id": cid,
                "school_id": meta.school_id if meta else None,
                "name": meta.name if meta else None,
                **agg,
            }
        )

    overall = _aggregate(inside, s.min_group_size, ds.district_exam_pass_percent)
    overall["eligible"] = eligible_total
    overall["participation_rate"] = (
        round(100.0 * overall["participants"] / eligible_total, 1) if eligible_total else None
    )
    overall["outside_participants"] = outside_count
    overall["pass_percent"] = ds.district_exam_pass_percent

    return {
        "exam": exam_row(exam),
        "overall": overall,
        "schools": school_rows,
        "classes": class_rows,
        "note_fa": (
            f"اعداد هر گروه فقط با حداقل {s.min_group_size} شرکت‌کننده نمایش داده می‌شود؛ "
            f"گروه‌های کوچک‌تر سرکوب (suppressed) می‌شوند (district spec §35)."
        ),
    }


# ------------------------- §21 تحلیل سؤال‌های آزمون -------------------------


def _point_biserial(correct: list[int], totals: list[float]) -> float | None:
    """قدرت تفکیک (point-biserial): همبستگی پاسخ درست هر سؤال با نمره کل."""
    n = len(totals)
    if n < 2:
        return None
    p = sum(correct) / n
    if p <= 0.0 or p >= 1.0:
        return None
    mean = sum(totals) / n
    sigma = math.sqrt(sum((t - mean) ** 2 for t in totals) / n)
    if sigma == 0:
        return None
    hi = [t for t, c in zip(totals, correct) if c]
    lo = [t for t, c in zip(totals, correct) if not c]
    if not hi or not lo:
        return None
    m_hi, m_lo = sum(hi) / len(hi), sum(lo) / len(lo)
    return round((m_hi - m_lo) / sigma * math.sqrt(p * (1 - p)), 3)


async def item_analysis(db: AsyncSession, exam: DistrictExam) -> dict:
    """برای هر سؤال: درصد پاسخ صحیح، دشواری تجربی، قدرت تفکیک، پرتکرارترین
    گزینه غلط + کج‌فهمی مرتبط، درصد خالی، میانگین زمان و علامت «نیازمند
    بازبینی» (§21)."""
    s = get_settings()
    ds = get_district_exam_settings()
    if exam.exam_id is None or exam.status == "draft":
        return {
            "exam": exam_row(exam),
            "items": [],
            "thresholds": {
                "discrimination": ds.item_review_discrimination,
                "difficulty_gap": ds.item_review_gap,
            },
            "note_fa": "آزمون هنوز منتشر نشده است؛ تحلیل سؤال پس از ثبت پاسخ محاسبه می‌شود.",
        }

    exam_items = list(
        (
            await db.execute(
                select(ExamItem)
                .options(selectinload(ExamItem.item).selectinload(QuestionItem.topic))
                .where(ExamItem.exam_id == exam.exam_id)
                .order_by(ExamItem.order)
            )
        ).scalars()
    )
    if not exam_items:
        return {
            "exam": exam_row(exam),
            "items": [],
            "thresholds": {
                "discrimination": ds.item_review_discrimination,
                "difficulty_gap": ds.item_review_gap,
            },
            "note_fa": "سؤالی برای این آزمون ثبت نشده است.",
        }

    item_ids = [ei.id for ei in exam_items]
    answers = list(
        (
            await db.execute(select(AttemptAnswer).where(AttemptAnswer.exam_item_id.in_(item_ids)))
        ).scalars()
    )
    by_item: dict[int, list[AttemptAnswer]] = {}
    for ans in answers:
        by_item.setdefault(ans.exam_item_id, []).append(ans)

    attempts = list(
        (
            await db.execute(
                select(ExamAttempt.id, ExamAttempt.percent).where(
                    ExamAttempt.exam_id == exam.exam_id, ExamAttempt.status == "graded"
                )
            )
        ).all()
    )
    totals_by_attempt = {aid: (pct or 0.0) for aid, pct in attempts}

    rows = []
    for ei in exam_items:
        item = ei.item
        ans_list = by_item.get(ei.id, [])
        n = len(ans_list)
        n_correct = sum(1 for a in ans_list if a.is_correct)
        n_blank = sum(1 for a in ans_list if a.selected_option is None)
        pct_correct = round(100.0 * n_correct / n, 1) if n else None
        empirical_p = round(n_correct / n, 3) if n else None
        prior_p = PRIOR_P_BY_DIFFICULTY.get(item.difficulty, 0.65)
        gap = round(abs(empirical_p - prior_p), 3) if empirical_p is not None else None

        # توزیع گزینه‌ها + پرتکرارترین گزینه غلط
        option_counts: dict[str, int] = {str(k): 0 for k in (item.options or {})}
        for a in ans_list:
            if a.selected_option is not None:
                option_counts[a.selected_option] = option_counts.get(a.selected_option, 0) + 1
        distractor_counts = {
            opt: cnt
            for opt, cnt in option_counts.items()
            if opt != item.correct_option and cnt > 0
        }
        top_distractor = None
        top_distractor_pct = None
        top_distractor_cause = None
        if distractor_counts:
            top_distractor = max(distractor_counts.items(), key=lambda kv: kv[1])[0]
            top_distractor_pct = round(100.0 * distractor_counts[top_distractor] / n, 1) if n else None
            causes = item.distractor_causes or {}
            top_distractor_cause = causes.get(top_distractor)

        # قدرت تفکیک روی نمره کل همان تلاش‌ها
        totals: list[float] = []
        correct_flags: list[int] = []
        for a in ans_list:
            if a.attempt_id in totals_by_attempt:
                totals.append(totals_by_attempt[a.attempt_id])
                correct_flags.append(1 if a.is_correct else 0)
        discrimination = _point_biserial(correct_flags, totals)

        avg_time_ms = (
            round(sum(a.time_spent_ms for a in ans_list) / n) if n else None
        )

        # علامت «نیازمند بازبینی» (§21): قدرت تفکیک پایین یا فاصله تجربی/پیشینی
        reasons: list[dict] = []
        insufficient = n < ds.item_min_responses
        if not insufficient:
            if discrimination is not None and discrimination < ds.item_review_discrimination:
                reasons.append(
                    {
                        "code": "discrimination",
                        "text": "قدرت تفکیک این سؤال بسیار پایین است؛ احتمالاً ایراد از سؤال است.",
                    }
                )
            if gap is not None and gap > ds.item_review_gap:
                reasons.append(
                    {
                        "code": "difficulty_gap",
                        "text": (
                            f"دشواری تجربی با دشواری پیش‌بینی‌شده فاصله زیادی دارد "
                            f"({gap} > {ds.item_review_gap})."
                        ),
                    }
                )

        rows.append(
            {
                "order": ei.order,
                "item_id": item.id,
                "body": item.body,
                "topic": item.topic.title_fa if item.topic is not None else None,
                "difficulty": item.difficulty,
                "prior_difficulty": prior_p,
                "responses": n,
                "pct_correct": pct_correct,
                "empirical_difficulty": empirical_p,
                "discrimination": discrimination,
                "blank_pct": round(100.0 * n_blank / n, 1) if n else None,
                "avg_time_ms": avg_time_ms,
                "option_counts": option_counts,
                "top_distractor": top_distractor,
                "top_distractor_pct": top_distractor_pct,
                "top_distractor_cause": top_distractor_cause,
                "misconception": item.misconception,
                "needs_review": bool(reasons),
                "review_reasons": reasons,
                "insufficient_data": insufficient,
            }
        )

    return {
        "exam": exam_row(exam),
        "items": rows,
        "thresholds": {
            "discrimination": ds.item_review_discrimination,
            "difficulty_gap": ds.item_review_gap,
            "min_responses": ds.item_min_responses,
        },
        "note_fa": (
            "سؤال با قدرت تفکیک زیر حد یا فاصله زیاد دشواری تجربی/پیشینی، "
            "نشان «نیازمند بازبینی» می‌گیرد (district spec §21)."
        ),
    }


# ------------------------- §25–§26 مداخله آموزشی و سنجش اثر -------------------------


async def topic_mastery_aggregate(
    db: AsyncSession, topic_id: int, school_ids: list[int]
) -> dict:
    """تجمیع تسط یک مبحث در مدارس هدف — با قاعده حداقل جمعیت."""
    s = get_settings()
    profiles = list(
        (
            await db.execute(select(StudentProfile).where(StudentProfile.school_id.in_(school_ids)))
        ).scalars()
    )
    student_ids = [p.user_id for p in profiles]
    states = (
        list(
            (
                await db.execute(
                    select(StudentTopicState).where(
                        StudentTopicState.topic_id == topic_id,
                        StudentTopicState.student_user_id.in_(student_ids),
                    )
                )
            ).scalars()
        )
        if student_ids
        else []
    )
    with_data = [st for st in states if st.evidence_count >= s.evidence_min_for_status]
    students = {st.student_user_id for st in with_data}
    suppressed = len(students) < s.min_group_size
    avg = (
        sum(st.effective_mastery for st in with_data) / len(with_data) if with_data else None
    )
    return {
        "students_with_data": len(students),
        "avg_mastery": None if suppressed or avg is None else round(avg, 1),
        "suppressed": suppressed,
        "min_group": s.min_group_size,
        "status_counts": (
            None
            if suppressed
            else _status_counts(with_data)
        ),
    }


def _status_counts(states: list[StudentTopicState]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for st in states:
        key = status_of(st.effective_mastery, st.evidence_count)
        counts[key] = counts.get(key, 0) + 1
    return counts


def effect_verdict(before: float | None, after: float | None, retention: float | None) -> dict:
    """سنجش اثر مداخله (§26) با سه نتیجه صریح:
    - effective: «اثر داشته» — رشد پس از بازآزمون + ماندگاری ~۳ هفته بعد
    - ineffective: «بی‌اثر» — بازآزمون بهبودی نشان نداد (مداخله بی‌اثر)
    - needs_attention: «نیاز به توجه» — رشد اولیه بود ولی ماندگار نماند
    و دو حالت گذار: pending (در انتظار بازآزمون) و needs_retention."""
    ds = get_district_exam_settings()
    out = {
        "verdict": "pending",
        "verdict_fa": "در انتظار بازآزمون",
        "delta_after": None,
        "delta_retention": None,
        "next_stage": "after",
        "min_gain": ds.intervention_min_gain,
        "retention_days": ds.intervention_retention_days,
    }
    if before is None or after is None:
        return out
    delta_after = round(after - before, 1)
    out["delta_after"] = delta_after
    if delta_after < ds.intervention_min_gain:
        out.update(
            verdict="ineffective",
            verdict_fa="بی‌اثر",
            next_stage=None,
        )
        return out
    if retention is None:
        out.update(
            verdict="needs_retention",
            verdict_fa="اثر اولیه — در انتظار سنجش ماندگاری",
            next_stage="retention",
        )
        return out
    delta_retention = round(retention - before, 1)
    out["delta_retention"] = delta_retention
    if delta_retention >= ds.intervention_min_gain:
        out.update(verdict="effective", verdict_fa="اثر داشته", next_stage=None)
    else:
        out.update(verdict="needs_attention", verdict_fa="نیاز به توجه", next_stage=None)
    return out


def intervention_row(iv: DistrictIntervention) -> dict:
    return {
        "id": iv.id,
        "district_id": iv.district_id,
        "title_fa": iv.title_fa,
        "type": iv.type,
        "type_fa": INTERVENTION_TYPE_FA.get(iv.type, iv.type),
        "topic_id": iv.topic_id,
        "grade": iv.grade,
        "start_date": iv.start_date,
        "end_date": iv.end_date,
        "before_mastery": iv.before_mastery,
        "after_mastery": iv.after_mastery,
        "retention_mastery": iv.retention_mastery,
        "after_measured_at": iv.after_measured_at,
        "retention_measured_at": iv.retention_measured_at,
        "status": iv.status,
        "status_fa": {"active": "در حال اجرا", "closed": "بسته‌شده", "cancelled": "لغوشده"}.get(
            iv.status, iv.status
        ),
        "notes": iv.notes,
        "created_by": iv.created_by,
        "created_at": iv.created_at,
        "closed_at": iv.closed_at,
        **effect_verdict(iv.before_mastery, iv.after_mastery, iv.retention_mastery),
    }


async def create_intervention(
    db: AsyncSession,
    *,
    district_id: int,
    created_by: int,
    title_fa: str,
    type: str,
    school_ids: list[int],
    topic_id: int | None = None,
    grade: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    before_mastery: float | None = None,
    notes: str | None = None,
) -> DistrictIntervention:
    """ثبت مداخله آموزشی (§25) با اندازه‌گیری «پیش از مداخله» — اگر داده
    نشود و مبحث مشخص باشد، از تجمیع SLM خوانده می‌شود (زیر حداقل جمعیت → 400)."""
    ds = get_district_exam_settings()
    if not title_fa.strip():
        raise HTTPException(400, "عنوان مداخله الزامی است")
    if type not in INTERVENTION_TYPES:
        raise HTTPException(400, f"نوع مداخله نامعتبر است ({', '.join(INTERVENTION_TYPES)})")
    schools_map = await _district_schools_map(db, school_ids, district_id)
    school_id_list = sorted(schools_map)

    if topic_id is not None and (await db.get(Topic, topic_id)) is None:
        raise HTTPException(404, "مبحث یافت نشد")

    if before_mastery is None:
        if topic_id is None:
            raise HTTPException(400, "برای سنجش «پیش از مداخله»، مبحث یا مقدار تسط را مشخص کنید")
        agg = await topic_mastery_aggregate(db, topic_id, school_id_list)
        if agg["suppressed"] or agg["avg_mastery"] is None:
            raise HTTPException(
                400,
                f"تسط این مبحث زیر حداقل جمعیت ({agg['min_group']} دانش‌آموز دارای داده) است؛ "
                "مقدار «پیش از مداخله» را دستی وارد کنید",
            )
        before_mastery = agg["avg_mastery"]
    if before_mastery is not None and not (0.0 <= before_mastery <= 100.0):
        raise HTTPException(400, "مقدار تسط باید بین ۰ تا ۱۰۰ باشد")

    start = start_date or date.today()
    end = end_date or (start + timedelta(days=ds.intervention_default_days))

    iv = DistrictIntervention(
        district_id=district_id,
        title_fa=title_fa.strip(),
        type=type,
        topic_id=topic_id,
        grade=grade,
        start_date=start,
        end_date=end,
        before_mastery=before_mastery,
        notes=notes.strip() if notes and notes.strip() else None,
        status="active",
        created_by=created_by,
    )
    db.add(iv)
    await db.flush()
    for sid in school_id_list:
        db.add(DistrictInterventionSchool(intervention_id=iv.id, school_id=sid))
    await db.flush()
    await log_action(
        db,
        actor_user_id=created_by,
        action="district_intervention_created",
        entity_type="district_intervention",
        entity_id=iv.id,
        detail=(
            f"district={district_id} type={type} topic={topic_id} "
            f"schools={len(school_id_list)} before={before_mastery}"
        ),
    )
    await db.flush()
    return iv


async def intervention_or_404(db: AsyncSession, iv_id: int, district_id: int) -> DistrictIntervention:
    iv = await db.get(DistrictIntervention, iv_id)
    if iv is None or iv.district_id != district_id:
        raise HTTPException(404, "مداخله یافت نشد")
    return iv


async def list_interventions(db: AsyncSession, district_id: int) -> list[dict]:
    ivs = list(
        (
            await db.execute(
                select(DistrictIntervention)
                .where(DistrictIntervention.district_id == district_id)
                .order_by(DistrictIntervention.id.desc())
            )
        ).scalars()
    )
    if not ivs:
        return []
    links = list(
        (
            await db.execute(
                select(DistrictInterventionSchool).where(
                    DistrictInterventionSchool.intervention_id.in_([iv.id for iv in ivs])
                )
            )
        ).scalars()
    )
    schools_by_iv: dict[int, list[int]] = {}
    for lk in links:
        schools_by_iv.setdefault(lk.intervention_id, []).append(lk.school_id)
    school_names = await _school_names(db, {sid for ids in schools_by_iv.values() for sid in ids})
    topic_titles = await _topic_titles(db, {iv.topic_id for iv in ivs if iv.topic_id})
    return [
        {
            **intervention_row(iv),
            "school_ids": sorted(schools_by_iv.get(iv.id, [])),
            "schools": [
                {"id": sid, "name": school_names.get(sid)} for sid in sorted(schools_by_iv.get(iv.id, []))
            ],
            "topic_title": topic_titles.get(iv.topic_id) if iv.topic_id else None,
        }
        for iv in ivs
    ]


async def record_intervention_measurement(
    db: AsyncSession,
    iv: DistrictIntervention,
    *,
    stage: str,
    mastery: float,
    actor_id: int,
) -> DistrictIntervention:
    """ثبت مرحله اندازه‌گیری چرخه §26: after (بازآزمون) یا retention (ماندگاری)."""
    if stage not in ("after", "retention"):
        raise HTTPException(400, "مرحله نامعتبر است (after | retention)")
    if not (0.0 <= mastery <= 100.0):
        raise HTTPException(400, "مقدار تسط باید بین ۰ تا ۱۰۰ باشد")
    if iv.status != "active":
        raise HTTPException(409, "این مدخل بسته شده است؛ اندازه‌گیری جدید پذیرفته نمی‌شود")
    if stage == "after":
        iv.after_mastery = mastery
        iv.after_measured_at = utcnow()
    else:
        if iv.after_mastery is None:
            raise HTTPException(409, "ابتدا سنجش «پس از مداخله» را ثبت کنید")
        iv.retention_mastery = mastery
        iv.retention_measured_at = utcnow()
    await log_action(
        db,
        actor_user_id=actor_id,
        action="district_intervention_measured",
        entity_type="district_intervention",
        entity_id=iv.id,
        detail=f"stage={stage} mastery={mastery}",
    )
    await db.flush()
    return iv


async def set_intervention_status(
    db: AsyncSession, iv: DistrictIntervention, status: str, actor_id: int
) -> DistrictIntervention:
    if status not in ("active", "closed", "cancelled"):
        raise HTTPException(400, "وضعیت نامعتبر است (active | closed | cancelled)")
    if iv.status == status:
        return iv
    previous = iv.status
    iv.status = status
    iv.closed_at = utcnow() if status in ("closed", "cancelled") else None
    await log_action(
        db,
        actor_user_id=actor_id,
        action=f"district_intervention_{status}",
        entity_type="district_intervention",
        entity_id=iv.id,
        detail=f"district={iv.district_id} from={previous}",
    )
    await db.flush()
    return iv


# ------------------------- §27 مأموریت برای مدارس -------------------------


def mission_status_fa(status: str) -> str:
    return {
        "active": "در حال اجرا",
        "completed": "تکمیل‌شده",
        "overdue": "عقب‌افتاده",
        "suppressed": "زیر حد نصاب",
    }.get(status, status)


async def _school_names(db: AsyncSession, school_ids: set[int]) -> dict[int, str]:
    if not school_ids:
        return {}
    rows = (await db.execute(select(School.id, School.name).where(School.id.in_(school_ids)))).all()
    return {sid: name for sid, name in rows}


async def _topic_titles(db: AsyncSession, topic_ids: set[int]) -> dict[int, str]:
    if not topic_ids:
        return {}
    rows = (await db.execute(select(Topic.id, Topic.title_fa).where(Topic.id.in_(topic_ids)))).all()
    return {tid: title for tid, title in rows}


async def create_mission(
    db: AsyncSession,
    *,
    district_id: int,
    created_by: int,
    title_fa: str,
    goal: str,
    topic_id: int,
    target_mastery: float,
    school_ids: list[int],
    deadline: date | None = None,
) -> DistrictMission:
    """تعریف مأموریت آموزشی مدارس (§27) + ممیزی «چه کسی ساخت»."""
    ds = get_district_exam_settings()
    if not title_fa.strip():
        raise HTTPException(400, "عنوان مأموریت الزامی است")
    if not goal.strip():
        raise HTTPException(400, "بیانیه هدف (goal) الزامی است")
    if not (0.0 <= target_mastery <= 100.0):
        raise HTTPException(400, "هدف تسط باید بین ۰ تا ۱۰۰ باشد")
    if (await db.get(Topic, topic_id)) is None:
        raise HTTPException(404, "مبحث یافت نشد")
    schools_map = await _district_schools_map(db, school_ids, district_id)

    mission = DistrictMission(
        district_id=district_id,
        title_fa=title_fa.strip(),
        goal=goal.strip(),
        topic_id=topic_id,
        target_mastery=target_mastery,
        deadline=deadline or (date.today() + timedelta(days=ds.mission_default_days)),
        created_by=created_by,
    )
    db.add(mission)
    await db.flush()
    for sid in schools_map:
        db.add(DistrictMissionSchool(mission_id=mission.id, school_id=sid))
    await db.flush()
    await log_action(
        db,
        actor_user_id=created_by,
        action="mission_created",
        entity_type="district_mission",
        entity_id=mission.id,
        detail=(
            f"district={district_id} topic={topic_id} target={target_mastery} "
            f"deadline={mission.deadline} schools={len(schools_map)}"
        ),
    )
    await db.flush()
    return mission


async def mission_or_404(db: AsyncSession, mission_id: int, district_id: int) -> DistrictMission:
    mission = await db.get(DistrictMission, mission_id)
    if mission is None or mission.district_id != district_id:
        raise HTTPException(404, "مأموریت یافت نشد")
    return mission


async def mission_progress(db: AsyncSession, mission: DistrictMission) -> dict:
    """داشبورد پیشرفت مأموریت: تسط هر مدرسه روی مبحث هدف (با سرکوب) +
    وضعیت مدرسه و کل مأموریت (در حال اجرا / تکمیل‌شده / عقب‌افتاده)."""
    s = get_settings()
    school_ids = sorted(
        row[0]
        for row in (
            await db.execute(
                select(DistrictMissionSchool.school_id).where(
                    DistrictMissionSchool.mission_id == mission.id
                )
            )
        ).all()
    )
    school_names = await _school_names(db, set(school_ids))
    topic = await db.get(Topic, mission.topic_id)
    today = date.today()

    rows = []
    for sid in school_ids:
        agg = await topic_mastery_aggregate(db, mission.topic_id, [sid])
        if agg["suppressed"] or agg["avg_mastery"] is None:
            school_status = "suppressed"
        elif agg["avg_mastery"] >= mission.target_mastery:
            school_status = "completed"
        elif mission.deadline < today:
            school_status = "overdue"
        else:
            school_status = "active"
        rows.append(
            {
                "school_id": sid,
                "name": school_names.get(sid),
                "students_with_data": agg["students_with_data"],
                "avg_mastery": agg["avg_mastery"],
                "suppressed": agg["suppressed"],
                "min_group": agg["min_group"],
                "status_counts": agg["status_counts"],
                "completed": school_status == "completed",
                "status": school_status,
                "status_fa": mission_status_fa(school_status),
            }
        )

    measurable = [r for r in rows if not r["suppressed"]]
    if measurable and all(r["completed"] for r in measurable):
        overall = "completed"
    elif mission.deadline < today:
        overall = "overdue"
    else:
        overall = "active"

    progress_avg = (
        round(sum(r["avg_mastery"] for r in measurable) / len(measurable), 1)
        if measurable
        else None
    )
    return {
        "id": mission.id,
        "district_id": mission.district_id,
        "title_fa": mission.title_fa,
        "goal": mission.goal,
        "topic_id": mission.topic_id,
        "topic_title": topic.title_fa if topic else None,
        "target_mastery": mission.target_mastery,
        "deadline": mission.deadline,
        "created_by": mission.created_by,
        "created_at": mission.created_at,
        "schools": rows,
        "schools_count": len(rows),
        "completed_count": sum(1 for r in rows if r["completed"]),
        "suppressed_count": sum(1 for r in rows if r["suppressed"]),
        "progress_avg": progress_avg,
        "status": overall,
        "status_fa": mission_status_fa(overall),
        "days_left": (mission.deadline - today).days,
        "note_fa": (
            f"پیشرفت هر مدرسه فقط با حداقل {s.min_group_size} دانش‌آموز دارای داده نمایش "
            "داده می‌شود (district spec §35)."
        ),
    }


async def list_missions(db: AsyncSession, district_id: int) -> list[dict]:
    missions = list(
        (
            await db.execute(
                select(DistrictMission)
                .where(DistrictMission.district_id == district_id)
                .order_by(DistrictMission.id.desc())
            )
        ).scalars()
    )
    return [await mission_progress(db, m) for m in missions]


# ------------------------- گزینه‌های مبحث (فرم‌های مداخله/مأموریت) -------------------------


async def topics_options(db: AsyncSession) -> list[dict]:
    rows = (
        await db.execute(
            select(Topic.id, Topic.title_fa, Book.subject, Book.grade)
            .join(Chapter, Chapter.id == Topic.chapter_id)
            .join(Book, Book.id == Chapter.book_id)
            .order_by(Book.subject, Topic.order)
        )
    ).all()
    return [
        {"id": tid, "title": title, "subject": subject, "grade": grade}
        for tid, title, subject, grade in rows
    ]
