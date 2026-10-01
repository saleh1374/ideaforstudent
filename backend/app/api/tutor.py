"""Tutor marketplace APIs (roadmap phase 8 «معلم خصوصی»): بازار، درخواست
جلسه، گروه‌ها و چت با فیلتر ایمنی زیر ۱۸ + گزارش پیام."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthUser, get_current_user
from app.core.db import get_db
from app.models.org import User
from app.models.tutoring import TutorGroup, TutorMessage, TutorProfile, TutorRequest
from app.services import tutoring as tutoring_svc

router = APIRouter(prefix="/tutor", tags=["tutor"])


@router.get("/market")
async def market(
    subject: str | None = None,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await tutoring_svc.market_list(db, subject)


class ProfileIn(BaseModel):
    headline: str | None = None
    subjects: list[str] = []
    bio: str | None = None
    session_price: int | None = None
    availability: str | None = None


@router.post("/profile")
async def upsert_profile(
    body: ProfileIn,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """فقط معلم می‌تواند نمایه بسازد (سند: بازار فقط معلمان فعال)."""
    if current.system_role != "teacher":
        raise HTTPException(403, "فقط معلمان می‌توانند نمایه بسازند")
    prof = (
        await db.execute(select(TutorProfile).where(TutorProfile.user_id == current.id))
    ).scalar_one_or_none()
    if prof is None:
        prof = TutorProfile(user_id=current.id)
        db.add(prof)
    prof.headline = body.headline
    prof.subjects = body.subjects
    prof.bio = body.bio
    prof.session_price = body.session_price
    prof.availability = body.availability
    prof.is_active = True
    await db.commit()
    return {"ok": True}


class RequestIn(BaseModel):
    tutor_user_id: int
    subject: str
    note: str | None = None


@router.post("/requests")
async def create_request(
    body: RequestIn,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current.system_role not in ("student", "parent"):
        raise HTTPException(403, "فقط دانش‌آموز یا والد می‌تواند درخواست دهد")
    tutor = await db.get(User, body.tutor_user_id)
    if tutor is None or tutor.system_role != "teacher":
        raise HTTPException(404, "معلم یافت نشد")
    req = TutorRequest(
        student_user_id=current.id,
        tutor_user_id=body.tutor_user_id,
        subject=body.subject,
        note=body.note,
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)
    return {"ok": True, "request_id": req.id, "status": req.status}


@router.get("/requests")
async def my_requests(
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(TutorRequest)
            .where(
                (TutorRequest.student_user_id == current.id) | (TutorRequest.tutor_user_id == current.id)
            )
            .order_by(TutorRequest.id.desc())
        )
    ).scalars().all()
    users = {u.id: u.full_name for u in (await db.execute(select(User))).scalars()}
    return {
        "requests": [
            {
                "id": r.id,
                "student_name": users.get(r.student_user_id),
                "tutor_name": users.get(r.tutor_user_id),
                "subject": r.subject,
                "note": r.note,
                "status": r.status,
            }
            for r in rows
        ]
    }


class DecisionIn(BaseModel):
    approve: bool


@router.post("/requests/{request_id}/decide")
async def decide(
    request_id: int,
    body: DecisionIn,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from datetime import datetime, timezone

    req = await db.get(TutorRequest, request_id)
    if req is None or req.tutor_user_id != current.id:
        raise HTTPException(404, "درخواست یافت نشد")
    if req.status != "pending":
        raise HTTPException(400, "قبلاً تصمیم گرفته شده")
    req.status = "accepted" if body.approve else "rejected"
    req.decided_at = datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True, "status": req.status}


# ---------------- گروه‌ها و چت ----------------


class GroupIn(BaseModel):
    title: str
    subject: str
    is_open: bool = True


@router.post("/groups")
async def create_group(
    body: GroupIn,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current.system_role != "teacher":
        raise HTTPException(403, "فقط معلم می‌تواند گروه بسازد")
    g = TutorGroup(tutor_user_id=current.id, title=body.title, subject=body.subject, is_open=body.is_open)
    db.add(g)
    await db.commit()
    await db.refresh(g)
    return {"ok": True, "group_id": g.id}


@router.get("/groups")
async def list_groups(
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    groups = (await db.execute(select(TutorGroup))).scalars().all()
    users = {u.id: u.full_name for u in (await db.execute(select(User))).scalars()}
    return {
        "groups": [
            {
                "id": g.id,
                "title": g.title,
                "subject": g.subject,
                "tutor_name": users.get(g.tutor_user_id),
                "is_open": g.is_open,
            }
            for g in groups
        ]
    }


@router.post("/groups/{group_id}/join")
async def join_group(
    group_id: int,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await tutoring_svc.join_group(db, group_id=group_id, student_user_id=current.id)
    if not result.get("ok"):
        raise HTTPException(400, result.get("reason"))
    await db.commit()
    return result


class MessageIn(BaseModel):
    content: str
    group_id: int | None = None
    request_id: int | None = None


@router.post("/messages")
async def send_message(
    body: MessageIn,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await tutoring_svc.send_message(
        db,
        sender_user_id=current.id,
        content=body.content,
        group_id=body.group_id,
        request_id=body.request_id,
    )
    if not result.get("ok"):
        raise HTTPException(400, result.get("reason"))
    await db.commit()
    return result


@router.get("/groups/{group_id}/messages")
async def group_messages(
    group_id: int,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(TutorMessage).where(TutorMessage.group_id == group_id).order_by(TutorMessage.id)
        )
    ).scalars().all()
    users = {u.id: u.full_name for u in (await db.execute(select(User))).scalars()}
    return {
        "messages": [
            {
                "id": m.id,
                "sender": users.get(m.sender_user_id),
                "content": m.content,
                "flagged": bool(m.flagged),
                "created_at": m.created_at,
            }
            for m in rows
        ]
    }


class ReportIn(BaseModel):
    reason: str


@router.post("/messages/{message_id}/report")
async def report_message(
    message_id: int,
    body: ReportIn,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await tutoring_svc.report_message(
        db, reporter_user_id=current.id, message_id=message_id, reason=body.reason
    )
    if not result.get("ok"):
        raise HTTPException(404, result.get("reason"))
    await db.commit()
    return result
