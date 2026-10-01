"""Teacher panel APIs (سند پنل معلم). دسترسی معلم فقط به کلاس‌های تخصیص‌یافته
خودش — دامنه محدود و شفاف (§18) + آزمون صلاحیت سالانه خودش (سند صلاحیت)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthUser, get_current_user
from app.core.db import get_db
from app.models.org import ClassRoom, ClassTeacherAssignment, School, StudentProfile
from app.models.teacher_assessment import TeacherExam, TeacherExamAttempt
from app.services import teacher as teacher_svc
from app.services import teacher_qualification as tq_svc

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
