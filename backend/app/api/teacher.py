"""Teacher panel APIs (سند پنل معلم). دسترسی معلم فقط به کلاس‌های تخصیص‌یافته
خودش — دامنه محدود و شفاف (§18)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthUser, get_current_user
from app.core.db import get_db
from app.models.org import ClassRoom, ClassTeacherAssignment, School, StudentProfile
from app.services import teacher as teacher_svc

router = APIRouter(prefix="/teacher", tags=["teacher"])


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
