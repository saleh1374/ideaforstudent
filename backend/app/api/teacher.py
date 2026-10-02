"""Teacher panel APIs (سند پنل معلم). دسترسی معلم فقط به کلاس‌های تخصیص‌یافته
خودش — دامنه محدود و شفاف (§18) + آزمون صلاحیت سالانه خودش (سند صلاحیت)
+ سازندهٔ آزمون هوشمند و تحلیل پس از آزمون (§8 و §10 سند پنل معلم)."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import AuthUser, get_current_user
from app.core.db import get_db
from app.models import exam_builder  # noqa: F401  (register new tables in Base.metadata)
from app.models import teacher_copilot  # noqa: F401  (register new tables in Base.metadata)
from app.models.assessment import Exam, ExamAttempt, ExamItem, QuestionItem
from app.models.catalog import Book, Topic
from app.models.exam_builder import ExamBuilderProfile
from app.models.org import ClassRoom, ClassTeacherAssignment, School, StudentProfile
from app.models.teacher_assessment import TeacherExam, TeacherExamAttempt
from app.models.teacher_copilot import TeacherSuggestion
from app.services import exam_builder as eb_svc
from app.services import teacher as teacher_svc
from app.services import teacher_copilot as tc_svc
from app.services import teacher_qualification as tq_svc
from app.services.rbac_service import has_permission_in_scope, log_action

router = APIRouter(prefix="/teacher", tags=["teacher"])


async def _owned_exam(exam_id: int, current: AuthUser, db: AsyncSession) -> TeacherExam:
    """آزمون صلاحیت فقط برای معلمِ خودش — معلم دیگر 403، ناموجود 404."""
    exam = await db.get(TeacherExam, exam_id)
    if exam is None:
        raise HTTPException(404, "آزمون یافت نشد")
    if exam.teacher_user_id != current.id and current.system_role != "platform_admin":
        raise HTTPException(403, "این آزمون به شما تخصیص نیافته است")
    return exam


async def _owned_class(class_id: int, current: AuthUser, db: AsyncSession) -> ClassRoom:
    if current.system_role == "platform_admin":
        cls = await db.get(ClassRoom, class_id)
        if cls is None:
            raise HTTPException(404, "کلاس یافت نشد")
        return cls
    link = (
        await db.execute(
            select(ClassTeacherAssignment).where(
                ClassTeacherAssignment.class_id == class_id,
                ClassTeacherAssignment.teacher_user_id == current.id,
                ClassTeacherAssignment.status == "active",
            )
        )
    ).scalar_one_or_none()
    if link is None:
        raise HTTPException(403, "این کلاس به شما تخصیص نیافته است")
    cls = await db.get(ClassRoom, class_id)
    if cls is None:
        raise HTTPException(404, "کلاس یافت نشد")
    return cls


@router.get("/me/classes")
async def my_classes(current: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    links = (
        await db.execute(
            select(ClassTeacherAssignment).where(
                ClassTeacherAssignment.teacher_user_id == current.id,
                ClassTeacherAssignment.status == "active",
            )
        )
    ).scalars().all()
    out = []
    for link in links:
        cls = await db.get(ClassRoom, link.class_id)
        school = await db.get(School, cls.school_id)
        profiles = (
            await db.execute(select(StudentProfile).where(StudentProfile.class_id == cls.id))
        ).scalars().all()
        out.append(
            {
                "class_id": cls.id,
                "name": cls.name,
                "grade": cls.grade,
                "subject": link.subject,
                "school_name": school.name if school else None,
                "students_count": len(profiles),
            }
        )
    return {"classes": out}


@router.get("/classes/{class_id}/radar")
async def class_radar(class_id: int, current: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _owned_class(class_id, current, db)
    return await teacher_svc.class_radar(db, class_id)


@router.get("/classes/{class_id}/root-cause/{topic_id}")
async def class_root_cause(
    class_id: int,
    topic_id: int,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _owned_class(class_id, current, db)
    return await teacher_svc.root_cause_chain(db, class_id, topic_id)


@router.get("/classes/{class_id}/groups")
async def class_groups(class_id: int, current: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _owned_class(class_id, current, db)
    return await teacher_svc.need_groups(db, class_id)


@router.get("/classes/{class_id}/students")
async def class_students(class_id: int, current: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _owned_class(class_id, current, db)
    data = await teacher_svc.need_groups(db, class_id)
    students = []
    for g in data["groups"]:
        for st in g["students"]:
            students.append({**st, "need": g["need"], "need_label": g["label"]})
    students.sort(key=lambda s: s["mastery"])
    return {"class_id": class_id, "students": students}


# ------------------- آزمون صلاحیت معلم (سند صلاحیت) -------------------


@router.get("/assessments")
async def my_assessments(
    current: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """نمای معلم از آزمون‌های صلاحیت سال جاری: هر آزمون + درصد تلاشِ
    تصحیح‌شده + رکورد صلاحیت مرتبط (یا null)."""
    return await tq_svc.teacher_assessments(db, current.id, tq_svc.current_school_year())


@router.get("/assessments/{exam_id}/questions")
async def assessment_questions(
    exam_id: int,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """سؤال‌های آزمون برای شرکت — هرگز شامل پاسخ درست نمی‌شود."""
    exam = await _owned_exam(exam_id, current, db)
    return {
        "exam": {
            "id": exam.id,
            "kind": exam.kind,
            "kind_fa": tq_svc.KIND_FA.get(exam.kind, exam.kind),
            "title_fa": exam.title_fa,
            "subject": exam.subject,
            "due_at": exam.due_at,
        },
        "items": await tq_svc.attempt_questions(db, exam),
    }


@router.post("/assessments/{exam_id}/start")
async def assessment_start(
    exam_id: int,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """شروع تلاش (idempotent تا زمان ارسال): معلمِ خودِ آزمون، در مهلت."""
    exam = await _owned_exam(exam_id, current, db)
    attempt = await tq_svc.start_attempt(db, exam, current.id)
    await db.commit()
    return {
        "ok": True,
        "attempt": {
            "id": attempt.id,
            "exam_id": attempt.exam_id,
            "status": attempt.status,
            "started_at": attempt.started_at,
        },
        "exam": tq_svc.exam_row(exam),
    }


class AnswerIn(BaseModel):
    item_id: int
    option: str | None = None


class SubmitIn(BaseModel):
    answers: list[AnswerIn]


@router.post("/assessments/{exam_id}/submit")
async def assessment_submit(
    exam_id: int,
    body: SubmitIn,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """ارسال و تصحیح آزمون: درصد + وضعیت آزمون + وضعیت صلاحیت (فقط وقتی
    هر دو آزمون تصحیح شده باشند، وگرنه null و صلاحیت pending می‌ماند)."""
    exam = await _owned_exam(exam_id, current, db)
    attempt = (
        await db.execute(
            select(TeacherExamAttempt).where(
                TeacherExamAttempt.exam_id == exam.id,
                TeacherExamAttempt.teacher_user_id == current.id,
            )
        )
    ).scalar_one_or_none()
    if attempt is None:
        raise HTTPException(409, "ابتدا آزمون را شروع کنید")
    result = await tq_svc.submit_attempt(db, attempt, [a.model_dump() for a in body.answers])
    await db.commit()
    return result


# ==============================================================================
# سازندهٔ آزمون هوشمند معلم + تحلیل پس از آزمون (سند پنل معلم §8 و §10)
# ==============================================================================


async def _class_exam_rights(db: AsyncSession, current: AuthUser, class_id: int) -> ClassRoom:
    """مجوز ساخت/انتشار آزمون روی یک کلاس: معلمِ فعالِ همان کلاس (مالکیت از
    طریق تخصیص کلاس) یا دارندهٔ مجوز create_exam در حوزهٔ همان کلاس."""
    if current.system_role == "platform_admin":
        cls = await db.get(ClassRoom, class_id)
        if cls is None:
            raise HTTPException(404, "کلاس یافت نشد")
        return cls
    link = (
        await db.execute(
            select(ClassTeacherAssignment).where(
                ClassTeacherAssignment.class_id == class_id,
                ClassTeacherAssignment.teacher_user_id == current.id,
                ClassTeacherAssignment.status == "active",
            )
        )
    ).scalar_one_or_none()
    if link is None and not await has_permission_in_scope(
        db, current.id, "create_exam", "class", class_id
    ):
        raise HTTPException(
            403, "برای ساخت آزمون در این کلاس باید معلم کلاس باشید یا مجوز create_exam داشته باشید"
        )
    cls = await db.get(ClassRoom, class_id)
    if cls is None:
        raise HTTPException(404, "کلاس یافت نشد")
    return cls


async def _accessible_exam(exam_id: int, current: AuthUser, db: AsyncSession) -> Exam:
    """دسترسی به آزمون سازنده: خودِ سازنده، platform_admin، یا دارندهٔ
    create_exam در حوزهٔ کلاس/مدرسهٔ آزمون — سایرین 403 (§10/§RBAC)."""
    exam = await db.get(Exam, exam_id)
    if exam is None:
        raise HTTPException(404, "آزمون یافت نشد")
    if current.system_role == "platform_admin" or exam.created_by == current.id:
        return exam
    if exam.class_id is not None and await has_permission_in_scope(
        db, current.id, "create_exam", "class", exam.class_id
    ):
        return exam
    if exam.school_id is not None and await has_permission_in_scope(
        db, current.id, "create_exam", "school", exam.school_id
    ):
        return exam
    raise HTTPException(403, "دسترسی لازم: create_exam")


def _draft(exam: Exam) -> None:
    """ویرایش/افزودن سؤال فقط روی پیش‌نویس (409 → toast + refresh در UI)."""
    if exam.status != "draft":
        raise HTTPException(409, "فقط آزمون پیش‌نویس قابل ویرایش است")


async def _profile_of(db: AsyncSession, exam_id: int) -> ExamBuilderProfile | None:
    return (
        await db.execute(
            select(ExamBuilderProfile).where(ExamBuilderProfile.exam_id == exam_id)
        )
    ).scalar_one_or_none()


async def _require_profile(db: AsyncSession, exam: Exam) -> ExamBuilderProfile:
    profile = await _profile_of(db, exam.id)
    if profile is None:
        profile = ExamBuilderProfile(exam_id=exam.id, mode="standard")
        db.add(profile)
        await db.flush()
    return profile


async def _exam_summary(db: AsyncSession, exam: Exam, profile: ExamBuilderProfile | None = None) -> dict:
    profile = profile if profile is not None else await _profile_of(db, exam.id)
    cls = await db.get(ClassRoom, exam.class_id) if exam.class_id else None
    item_ids = (await db.execute(select(ExamItem.id).where(ExamItem.exam_id == exam.id))).scalars().all()
    attempt_ids = (
        await db.execute(select(ExamAttempt.id).where(ExamAttempt.exam_id == exam.id))
    ).scalars().all()
    mode = profile.mode if profile else "standard"
    return {
        "id": exam.id,
        "title_fa": exam.title_fa,
        "exam_type": exam.exam_type,
        "type_fa": eb_svc.EXAM_TYPES_FA.get(exam.exam_type, exam.exam_type),
        "mode": mode,
        "mode_fa": eb_svc.MODES_FA.get(mode, mode),
        "status": exam.status,
        "class_id": exam.class_id,
        "class_name": cls.name if cls else None,
        "subject": exam.subject,
        "grade": exam.grade,
        "scope": exam.scope,
        "opens_at": exam.opens_at,
        "closes_at": exam.closes_at,
        "negative_marking_k": exam.negative_marking_k,
        "item_count": len(item_ids),
        "attempts_count": len(attempt_ids),
        "goal": profile.goal if profile else None,
        "has_blueprint": bool(exam.blueprint),
    }


async def _class_subject(db: AsyncSession, cls: ClassRoom) -> str | None:
    """درس کلاس: از تخصیص فعال معلم‌ها، وگرنه از کتاب همان پایه."""
    link = (
        await db.execute(
            select(ClassTeacherAssignment)
            .where(ClassTeacherAssignment.class_id == cls.id, ClassTeacherAssignment.status == "active")
            .limit(1)
        )
    ).scalar_one_or_none()
    if link is not None and link.subject:
        return link.subject
    book = (
        await db.execute(select(Book).where(Book.grade == cls.grade).limit(1))
    ).scalar_one_or_none()
    return book.subject if book else None


class CreateExamIn(BaseModel):
    title_fa: str
    class_id: int
    exam_type: str = "class_exam"
    mode: str = "standard"
    subject: str | None = None
    opens_at: datetime | None = None
    closes_at: datetime | None = None
    negative_marking_k: float = 0.0


class BlueprintRowIn(BaseModel):
    topic_id: int
    count: int
    item_kind: str = "concept_base"
    diagnostic_purpose: str = ""


class PatchExamIn(BaseModel):
    title_fa: str | None = None
    exam_type: str | None = None
    mode: str | None = None
    opens_at: datetime | None = None
    closes_at: datetime | None = None
    negative_marking_k: float | None = None
    blueprint: list[BlueprintRowIn] | None = None


class BlueprintIn(BaseModel):
    goal: str
    topic_id: int | None = None


class AddItemIn(BaseModel):
    source: str = "blueprint"  # blueprint | bank | custom
    item_id: int | None = None          # bank
    body: str | None = None             # custom
    options: dict[str, str] | None = None
    correct_option: str | None = None
    distractor_causes: dict[str, str] | None = None
    topic_id: int | None = None
    points: float = 1.0
    difficulty: str = "medium"
    misconception: str | None = None


class ItemPatchIn(BaseModel):
    points: float | None = None
    order: int | None = None


@router.get("/exams")
async def my_builder_exams(current: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """فهرست آزمون‌های ساخته‌شده توسط خود معلم (مالکیت §RBAC)."""
    q = select(Exam).order_by(Exam.id.desc())
    if current.system_role != "platform_admin":
        q = q.where(Exam.created_by == current.id)
    exams = (await db.execute(q)).scalars().all()
    return {"exams": [await _exam_summary(db, e) for e in exams]}


@router.post("/exams")
async def create_builder_exam(
    body: CreateExamIn,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """ساخت پیش‌نویس آزمون برای یک کلاسِ خودِ معلم (§8.1 انواع، §8.4 نمرهٔ منفی)."""
    title = (body.title_fa or "").strip()
    if not title:
        raise HTTPException(400, "عنوان آزمون الزامی است")
    if body.exam_type not in eb_svc.EXAM_TYPE_KEYS:
        raise HTTPException(400, "نوع آزمون نامعتبر است")
    if body.mode not in eb_svc.MODE_KEYS:
        raise HTTPException(400, "حالت آزمون نامعتبر است")
    if not 0.0 <= body.negative_marking_k <= 1.0:
        raise HTTPException(400, "ضریب نمرهٔ منفی (k) باید بین ۰ تا ۱ باشد")
    if body.opens_at is not None and body.closes_at is not None and body.opens_at >= body.closes_at:
        raise HTTPException(400, "زمان پایان آزمون باید بعد از زمان شروع باشد")

    cls = await _class_exam_rights(db, current, body.class_id)
    subject = body.subject or await _class_subject(db, cls)
    if not subject:
        raise HTTPException(400, "درس کلاس مشخص نیست؛ subject را صریح ارسال کنید")

    exam = Exam(
        title_fa=title,
        exam_type=body.exam_type,
        grade=cls.grade,
        subject=subject,
        scope="class",
        school_id=cls.school_id,
        class_id=cls.id,
        status="draft",
        opens_at=body.opens_at,
        closes_at=body.closes_at,
        negative_marking_k=body.negative_marking_k,
        created_by=current.id,
    )
    db.add(exam)
    await db.flush()
    db.add(ExamBuilderProfile(exam_id=exam.id, mode=body.mode))
    await log_action(
        db,
        actor_user_id=current.id,
        action="teacher_exam_created",
        entity_type="exam",
        entity_id=exam.id,
        detail=f"type={body.exam_type} mode={body.mode} class={cls.id}",
    )
    await db.commit()
    return {"ok": True, "exam": await _exam_summary(db, exam)}


@router.get("/exams/{exam_id}")
async def builder_exam_detail(
    exam_id: int,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """جزئیات آزمون سازنده: مشخصات + هدف/بلوپرینت + سؤال‌ها (با پاسخ درست
    — فقط خودِ سازنده یا دارندهٔ create_exam در حوزه)."""
    exam = await _accessible_exam(exam_id, current, db)
    profile = await _profile_of(db, exam.id)
    blueprint = await eb_svc.decorate_blueprint(db, exam.blueprint or []) if exam.blueprint else []
    exam_items = (
        await db.execute(
            select(ExamItem)
            .options(selectinload(ExamItem.item))
            .where(ExamItem.exam_id == exam.id)
            .order_by(ExamItem.order)
        )
    ).scalars().all()
    topic_ids = {ei.item.topic_id for ei in exam_items}
    topic_titles = {
        t.id: t.title_fa for t in (await db.execute(select(Topic).where(Topic.id.in_(topic_ids)))).scalars()
    } if topic_ids else {}
    items = [
        {
            "exam_item_id": ei.id,
            "item_id": ei.item_id,
            "order": ei.order,
            "points": ei.points,
            "body": ei.item.body,
            "options": ei.item.options,
            "correct_option": ei.item.correct_option,
            "distractor_causes": ei.item.distractor_causes or {},
            "difficulty": ei.item.difficulty,
            "misconception": ei.item.misconception,
            "topic_id": ei.item.topic_id,
            "topic_title": topic_titles.get(ei.item.topic_id, "—"),
        }
        for ei in exam_items
    ]
    return {
        "exam": await _exam_summary(db, exam, profile),
        "goal": profile.goal if profile else None,
        "blueprint": blueprint,
        "items": items,
    }


@router.patch("/exams/{exam_id}")
async def patch_builder_exam(
    exam_id: int,
    body: PatchExamIn,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """ویرایش پیش‌نویس: عنوان/نوع/حالت/پنجرهٔ برگزاری/k + بلوپرینت ویرایش‌شده."""
    exam = await _accessible_exam(exam_id, current, db)
    _draft(exam)

    if body.title_fa is not None and not body.title_fa.strip():
        raise HTTPException(400, "عنوان آزمون نمی‌تواند خالی باشد")
    if body.exam_type is not None and body.exam_type not in eb_svc.EXAM_TYPE_KEYS:
        raise HTTPException(400, "نوع آزمون نامعتبر است")
    if body.mode is not None and body.mode not in eb_svc.MODE_KEYS:
        raise HTTPException(400, "حالت آزمون نامعتبر است")
    if body.negative_marking_k is not None and not 0.0 <= body.negative_marking_k <= 1.0:
        raise HTTPException(400, "ضریب نمرهٔ منفی (k) باید بین ۰ تا ۱ باشد")

    new_opens = body.opens_at if body.opens_at is not None else exam.opens_at
    new_closes = body.closes_at if body.closes_at is not None else exam.closes_at
    if new_opens is not None and new_closes is not None and new_opens >= new_closes:
        raise HTTPException(400, "زمان پایان آزمون باید بعد از زمان شروع باشد")

    if body.blueprint is not None:
        try:
            cleaned = eb_svc.validate_blueprint([r.model_dump() for r in body.blueprint])
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        if cleaned:
            ids = [r["topic_id"] for r in cleaned]
            known = set((await db.execute(select(Topic.id).where(Topic.id.in_(ids)))).scalars())
            if any(i not in known for i in ids):
                raise HTTPException(400, "مبحثی از بلوپرینت در کاتالوگ یافت نشد")
        exam.blueprint = cleaned

    if body.title_fa is not None:
        exam.title_fa = body.title_fa.strip()
    if body.exam_type is not None:
        exam.exam_type = body.exam_type
    if body.opens_at is not None:
        exam.opens_at = body.opens_at
    if body.closes_at is not None:
        exam.closes_at = body.closes_at
    if body.negative_marking_k is not None:
        exam.negative_marking_k = body.negative_marking_k
    if body.mode is not None:
        profile = await _require_profile(db, exam)
        profile.mode = body.mode

    await db.commit()
    return {"ok": True, "exam": await _exam_summary(db, exam)}


@router.post("/exams/{exam_id}/blueprint")
async def propose_exam_blueprint(
    exam_id: int,
    body: BlueprintIn,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """§8.2 ساخت بر پایهٔ هدف: هدف متنی معلم ← ردیف‌های بلوپرینت قطعی
    (مبحث هدف + پیش‌نیازها + توضیح فارسی هر ردیف)."""
    exam = await _accessible_exam(exam_id, current, db)
    _draft(exam)
    goal = (body.goal or "").strip()
    if not goal:
        raise HTTPException(400, "متن هدف آزمون الزامی است؛ هدف را به زبان ساده بنویسید")

    proposal = await eb_svc.propose_blueprint(
        db,
        goal=goal,
        exam_type=exam.exam_type,
        topic_id=body.topic_id,
        grade=exam.grade,
        subject=exam.subject,
    )
    if not proposal.get("ok"):
        raise HTTPException(400, proposal.get("reason") or "بلوپرینت قابل پیشنهاد نیست")

    exam.blueprint = [
        {
            "topic_id": r["topic_id"],
            "item_kind": r["item_kind"],
            "count": r["count"],
            "diagnostic_purpose": r["diagnostic_purpose"],
        }
        for r in proposal["rows"]
    ]
    profile = await _require_profile(db, exam)
    profile.goal = goal
    await db.commit()
    return {
        "ok": True,
        "goal": goal,
        "target_topic": proposal["target_topic"],
        "rows": proposal["rows"],
        "summary_fa": proposal["summary_fa"],
    }


@router.post("/exams/{exam_id}/items")
async def add_exam_item(
    exam_id: int,
    body: AddItemIn,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """افزودن سؤال: از روی بلوپرینت (مونتاژ هوشمند از بانک)، مستقیم از بانک،
    یا سؤال دستی با علت هر گزینهٔ غلط (§5.3/§8.2). پاسخ نرم برای کسری بانک."""
    exam = await _accessible_exam(exam_id, current, db)
    _draft(exam)

    if body.source == "blueprint":
        if not exam.blueprint:
            raise HTTPException(400, "ابتدا از روی هدف، بلوپرینت پیشنهاد بگیرید")
        result = await eb_svc.assemble_from_blueprint(db, exam)
        await db.commit()
        return result  # 200 با {ok:false, reason} وقتی بانک کسری دارد

    async def attach(item_id: int, points: float) -> ExamItem:
        order_vals = (
            await db.execute(select(ExamItem.order).where(ExamItem.exam_id == exam.id))
        ).scalars().all()
        ei = ExamItem(
            exam_id=exam.id,
            item_id=item_id,
            order=(max(order_vals) + 1) if order_vals else 1,
            points=points,
        )
        db.add(ei)
        await db.flush()
        return ei

    if body.source == "bank":
        if body.item_id is None:
            raise HTTPException(400, "شناسهٔ سؤال بانک الزامی است")
        q = await db.get(QuestionItem, body.item_id)
        if q is None or not q.is_active:
            raise HTTPException(404, "سؤال در بانک یافت نشد یا غیرفعال است")
        already = (
            await db.execute(
                select(ExamItem.id).where(ExamItem.exam_id == exam.id, ExamItem.item_id == q.id)
            )
        ).scalar_one_or_none()
        if already is not None:
            raise HTTPException(409, "این سؤال قبلاً به آزمون اضافه شده است")
        points = body.points if body.points > 0 else 1.0
        ei = await attach(q.id, points)
        await db.commit()
        return {"ok": True, "attached": 1, "exam_item_id": ei.id, "order": ei.order}

    if body.source == "custom":
        if not (body.body or "").strip():
            raise HTTPException(400, "متن سؤال الزامی است")
        opts = body.options or {}
        letters = ["A", "B", "C", "D"]
        if any(not str(opts.get(l) or "").strip() for l in letters):
            raise HTTPException(400, "هر چهار گزینه باید متن داشته باشند")
        if body.correct_option not in letters:
            raise HTTPException(400, "گزینهٔ درست باید یکی از A تا D باشد")
        for key, cause in (body.distractor_causes or {}).items():
            if key not in letters or key == body.correct_option:
                raise HTTPException(400, "علت خطا فقط برای گزینه‌های غلط قابل ثبت است")
            if key not in opts:
                raise HTTPException(400, "گزینه‌ای با این حرف وجود ندارد")
            if cause not in eb_svc.CAUSE_FA:
                raise HTTPException(400, "علت خطا نامعتبر است؛ فقط شش علت استاندارد مجاز است")
        if body.difficulty not in ("easy", "medium", "hard"):
            raise HTTPException(400, "دشواری سؤال باید easy، medium یا hard باشد")
        if not 0.0 < body.points <= 100.0:
            raise HTTPException(400, "امتیاز سؤال باید بزرگ‌تر از صفر و حداکثر ۱۰۰ باشد")

        topic_id = body.topic_id
        if topic_id is None and exam.blueprint:
            topic_id = exam.blueprint[0].get("topic_id")
        if topic_id is None:
            raise HTTPException(400, "مبحث سؤال را مشخص کنید یا ابتدا بلوپرینت بسازید")
        topic = await db.get(Topic, topic_id)
        if topic is None:
            raise HTTPException(400, "مبحث انتخاب‌شده در کاتالوگ یافت نشد")

        q = QuestionItem(
            topic_id=topic.id,
            body=body.body.strip(),
            options={l: str(opts[l]).strip() for l in letters},
            correct_option=body.correct_option,
            difficulty=body.difficulty,
            difficulty_weight={"easy": 1.0, "medium": 1.2, "hard": 1.5}[body.difficulty],
            misconception=(body.misconception or "").strip() or None,
            distractor_causes=dict(body.distractor_causes or {}),
            is_active=1,
        )
        db.add(q)
        await db.flush()
        ei = await attach(q.id, body.points)
        await db.commit()
        return {"ok": True, "attached": 1, "exam_item_id": ei.id, "item_id": q.id, "order": ei.order}

    raise HTTPException(400, "منبع سؤال نامعتبر است (blueprint | bank | custom)")


@router.patch("/exams/{exam_id}/items/{exam_item_id}")
async def patch_exam_item(
    exam_id: int,
    exam_item_id: int,
    body: ItemPatchIn,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """ویرایش سؤال آزمون: امتیاز و ترتیب (قید یکتایی ترتیب با فاز موقت رعایت می‌شود)."""
    exam = await _accessible_exam(exam_id, current, db)
    _draft(exam)
    ei = await db.get(ExamItem, exam_item_id)
    if ei is None or ei.exam_id != exam.id:
        raise HTTPException(404, "سؤال در این آزمون یافت نشد")
    if body.points is not None:
        if not 0.0 < body.points <= 100.0:
            raise HTTPException(400, "امتیاز سؤال باید بزرگ‌تر از صفر و حداکثر ۱۰۰ باشد")
        ei.points = body.points
    if body.order is not None:
        if body.order < 1:
            raise HTTPException(400, "ترتیب سؤال باید ۱ یا بیشتر باشد")
        items = sorted(
            (await db.execute(select(ExamItem).where(ExamItem.exam_id == exam.id))).scalars().all(),
            key=lambda x: (x.order, x.id),
        )
        rest = [it for it in items if it.id != ei.id]
        rest.insert(min(body.order - 1, len(rest)), ei)
        # فاز ۱: سفارش‌های موقت یکتا — تا هنگام جابه‌جایی، قید یکتایی نقض نشود
        for idx, it in enumerate(rest):
            it.order = -(idx + 1)
        await db.flush()
        for idx, it in enumerate(rest):
            it.order = idx + 1
    await db.commit()
    return {"ok": True, "order": ei.order, "points": ei.points}


@router.delete("/exams/{exam_id}/items/{exam_item_id}")
async def delete_exam_item(
    exam_id: int,
    exam_item_id: int,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """حذف سؤال از پیش‌نویس آزمون."""
    exam = await _accessible_exam(exam_id, current, db)
    _draft(exam)
    ei = await db.get(ExamItem, exam_item_id)
    if ei is None or ei.exam_id != exam.id:
        raise HTTPException(404, "سؤال در این آزمون یافت نشد")
    await db.delete(ei)
    await db.commit()
    return {"ok": True}


@router.post("/exams/{exam_id}/publish")
async def publish_exam(
    exam_id: int,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """انتشار آزمون (§8.3): استاندارد ← scope=class (ورود به برد)؛
    تشخیصی شخصی ← scope=personal (فقط SLM، بدون برد). مالک یا create_exam."""
    exam = await _accessible_exam(exam_id, current, db)
    if exam.status != "draft":
        raise HTTPException(409, "این آزمون قبلاً منتشر شده است")
    item_count = len(
        (await db.execute(select(ExamItem.id).where(ExamItem.exam_id == exam.id))).scalars().all()
    )
    if item_count == 0:
        raise HTTPException(400, "برای انتشار باید دست‌کم یک سؤال به آزمون اضافه کنید")
    if exam.opens_at is not None and exam.closes_at is not None and exam.opens_at >= exam.closes_at:
        raise HTTPException(400, "زمان پایان آزمون باید بعد از زمان شروع باشد")
    if exam.closes_at is not None and exam.closes_at < datetime.utcnow():
        raise HTTPException(400, "مهلت پایان آزمون گذشته است؛ ابتدا مهلت را اصلاح کنید")
    if exam.opens_at is None:
        exam.opens_at = datetime.utcnow()

    profile = await _profile_of(db, exam.id)
    mode = profile.mode if profile else "standard"
    exam.status = "published"
    exam.scope = "class" if mode == "standard" else "personal"
    await log_action(
        db,
        actor_user_id=current.id,
        action="teacher_exam_published",
        entity_type="exam",
        entity_id=exam.id,
        detail=f"mode={mode} items={item_count} scope={exam.scope}",
    )
    await db.commit()
    summary = await _exam_summary(db, exam, profile)
    note = (
        "آزمون منتشر شد؛ در فهرست دانش‌آموزان قابل مشاهده و شرکت است."
        if mode == "standard"
        else "حالت تشخیصی شخصی: نتایج فقط SLM دانش‌آموزان را به‌روزرسانی می‌کند و وارد برد نمی‌شود."
    )
    return {"ok": True, "exam": summary, "note_fa": note}


@router.get("/exams/{exam_id}/item-analysis")
async def exam_item_analysis(
    exam_id: int,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """§10.1/§10.2 تحلیل پس از آزمون هر سؤال + پرچم «نیازمند بازبینی».
    فقط مالک آزمون یا دارندهٔ create_exam در حوزهٔ آن — سایرین 403."""
    exam = await _accessible_exam(exam_id, current, db)
    result = await eb_svc.compute_item_analysis(db, exam)
    await db.commit()
    return result


# ------------------------- دستیار هوشمند معلم (§15 و §16) -------------------------


class TCopilotChatIn(BaseModel):
    message: str
    conversation_id: int | None = None


@router.post("/classes/{class_id}/copilot/chat")
async def teacher_copilot_chat(
    class_id: int,
    body: TCopilotChatIn,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """§15 پرسش/پاسخ تحلیلی معلم روی برش تجمیعی همان کلاس (نه SLM یک
    دانش‌آموز): تشخیص نیت → بازیابی از تجمیع‌های واقعی → پاسخ با «منابع».
    درخواست ساخت آزمون «کارت پیشنهاد» می‌سازد و بدون تأیید معلم چیزی
    ساخته نمی‌شود (§16). هر پرسش با رویداد teacher_copilot_query در لاگ
    ممیزی ثبت می‌شود."""
    await _owned_class(class_id, current, db)
    message = body.message.strip()
    if not message:
        raise HTTPException(400, "متن پرسش نمی‌تواند خالی باشد")

    result = await tc_svc.chat(
        db,
        class_id=class_id,
        actor_user_id=current.id,
        message=message,
        conversation_id=body.conversation_id,
    )
    await log_action(
        db,
        actor_user_id=current.id,
        action="teacher_copilot_query",
        entity_type="class",
        entity_id=class_id,
        detail=f"intent={result['intent']} conv={result['conversation_id']}",
    )
    await db.commit()
    return result


@router.get("/classes/{class_id}/copilot/conversations")
async def teacher_copilot_conversations(
    class_id: int,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """فهرست گفت‌وگوهای قبلی معلم با کوپایلت (فقط همین کلاس)."""
    await _owned_class(class_id, current, db)
    return {"conversations": await tc_svc.list_conversations(db, class_id)}


@router.get("/classes/{class_id}/copilot/conversations/{conversation_id}")
async def teacher_copilot_conversation_detail(
    class_id: int,
    conversation_id: int,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """پیام‌های یک گفت‌وگو — گفت‌وگوی کلاس دیگر یا ناشناس → 404."""
    await _owned_class(class_id, current, db)
    data = await tc_svc.conversation_messages(db, class_id, conversation_id)
    if data is None:
        raise HTTPException(404, "گفت‌وگو یافت نشد")
    return data


def _suggestion_row(s: TeacherSuggestion) -> dict:
    return {
        "id": s.id,
        "class_id": s.class_id,
        "kind": s.kind,
        "title_fa": s.title_fa,
        "evidence_fa": s.evidence_fa,
        "actions_fa": list(s.actions_fa or []),
        "status": s.status,
        "final_actions_fa": list(s.final_actions_fa) if s.final_actions_fa else None,
        "result": s.result,
        "decided_by": s.decided_by,
        "decided_at": s.decided_at,
        "decision_note": s.decision_note,
        "created_at": s.created_at,
    }


@router.get("/classes/{class_id}/suggestions")
async def list_teacher_suggestions(
    class_id: int,
    status: str | None = None,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """§16 پیشنهادهای اقدام کلاس — «ساخته‌شده توسط سیستم، اجراشده فقط با
    تصمیم معلم». فیلتر وضعیت اختیاری (proposed|approved|edited|rejected)."""
    await _owned_class(class_id, current, db)
    if status is not None and status not in ("proposed", "approved", "edited", "rejected"):
        raise HTTPException(400, "وضعیت نامعتبر است")
    q = select(TeacherSuggestion).where(TeacherSuggestion.class_id == class_id)
    if status is not None:
        q = q.where(TeacherSuggestion.status == status)
    rows = (await db.execute(q.order_by(TeacherSuggestion.id.desc()))).scalars().all()
    return {"suggestions": [_suggestion_row(s) for s in rows]}


@router.post("/classes/{class_id}/suggestions/generate")
async def generate_teacher_suggestions(
    class_id: int,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """ساخت پیشنهاد اقدام از داده واقعی کلاس (ضعیف‌ترین مبحث، گروه مداخله،
    گروه افت ماندگاری) — idempotent: پیشنهاد بازِ همان عنوان تکرار نمی‌شود."""
    await _owned_class(class_id, current, db)
    created = await tc_svc.generate_suggestions(db, class_id)
    await db.commit()
    return {
        "ok": True,
        "created": len(created),
        "suggestions": [_suggestion_row(s) for s in created],
    }


class TSuggestionDecisionIn(BaseModel):
    action: str  # approve | edit | reject
    edited_actions: list[str] | None = None
    note: str | None = None


@router.post("/classes/{class_id}/suggestions/{suggestion_id}/decide")
async def decide_teacher_suggestion(
    class_id: int,
    suggestion_id: int,
    body: TSuggestionDecisionIn,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """§16 اختیار کامل معلم: تأیید، ویرایش یا رد پیشنهاد — با رویداد
    ممیزی ai_suggestion_approved/edited/rejected. تأیید «ساخت آزمون» یا
    «ارسال تمرین» اجرای واقعی را در همان تراکنش انجام می‌دهد؛ بدون تأیید
    هیچ‌چیزی اجرا نمی‌شود. خارج از کلاس → 404؛ تصمیم تکراری → 409؛
    عملیات نامعتبر → 400."""
    if body.action not in ("approve", "edit", "reject"):
        raise HTTPException(400, "عملیات نامعتبر است (approve|edit|reject)")
    await _owned_class(class_id, current, db)
    try:
        sugg = await tc_svc.decide_suggestion(
            db,
            class_id=class_id,
            suggestion_id=suggestion_id,
            actor_user_id=current.id,
            action=body.action,
            edited_actions=body.edited_actions,
            note=body.note,
        )
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(409, str(exc))
    if sugg is None:
        raise HTTPException(404, "پیشنهاد یافت نشد")

    await log_action(
        db,
        actor_user_id=current.id,
        action={
            "approve": "ai_suggestion_approved",
            "edit": "ai_suggestion_edited",
            "reject": "ai_suggestion_rejected",
        }[body.action],
        entity_type="teacher_suggestion",
        entity_id=sugg.id,
        detail=f"class={class_id} kind={sugg.kind} note={body.note or ''}",
    )
    await db.commit()
    return {"ok": True, "suggestion": _suggestion_row(sugg)}


@router.get("/my-schedule")
async def my_schedule(
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """برنامه هفتگی همه کلاس‌های معلم + شیفت و بار هفتگی — از همان ردیف‌های
    برنامه کلاس‌ها (همگام با پنل مدیر)."""
    from app.services import school_ops

    return await school_ops.teacher_schedule(db, current.id)
