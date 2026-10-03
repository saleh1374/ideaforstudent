"""Tutor marketplace APIs (roadmap phase 8 «معلم خصوصی»): بازار، درخواست
جلسه، گروه‌ها و چت با فیلتر ایمنی زیر ۱۸ + گزارش پیام."""
from datetime import datetime

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

# نقش‌هایی که می‌توانند مدارک صالحیت معلم خصوصی را بررسی کنند (§10.2-س)
_VERIFIER_ROLES = ("platform_admin", "ministry", "province_admin", "district_admin")


@router.get("/market")
async def market(
    subject: str | None = None,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await tutoring_svc.market_list(
        db, subject, viewer_user_id=current.id, viewer_role=current.system_role
    )


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
    # والد از جانب فرزندش درخواست می‌دهد؛ رضایت لازم نیست (خودِ والد است)
    student_user_id = current.id
    if current.system_role == "parent":
        from app.models.org import ParentLink

        link = (
            await db.execute(
                select(ParentLink).where(
                    ParentLink.parent_user_id == current.id, ParentLink.status == "active"
                )
            )
        ).scalars().first()
        if link is None:
            raise HTTPException(400, "ابتدا فرزند خود را به حساب متصل کنید")
        student_user_id = link.student_user_id
    result = await tutoring_svc.create_request(
        db,
        student_user_id=student_user_id,
        tutor_user_id=body.tutor_user_id,
        subject=body.subject,
        note=body.note,
    )
    if not result.get("ok"):
        raise HTTPException(400, result.get("reason"))
    await db.commit()
    return result


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
    out = []
    for r in rows:
        consent = await tutoring_svc.get_consent(db, r.id)
        state = await tutoring_svc.request_state(r, consent)
        # تا والد تأیید نکند، درخواست به معلم نمی‌رسد (§10.2-۵)
        if r.tutor_user_id == current.id and not state["visible_to_tutor"]:
            continue
        out.append(
            {
                "id": r.id,
                "student_name": users.get(r.student_user_id),
                "tutor_name": users.get(r.tutor_user_id),
                "subject": r.subject,
                "note": r.note,
                "status": r.status,
                "state": state["state"],
                "state_fa": state["state_fa"],
                "expires_at": state["expires_at"],
                "hours_left": state["hours_left"],
                "requires_parent_consent": consent is not None,
                "consent_status": consent.status if consent else None,
            }
        )
    return {"requests": out}


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
    consent = await tutoring_svc.get_consent(db, request_id)
    if consent is not None and consent.status != "approved":
        raise HTTPException(400, "این درخواست هنوز به تأیید والد نرسیده است")
    if tutoring_svc.is_expired(req):
        raise HTTPException(400, "مهلت ۷۲ ساعته پاسخ گذشته و درخواست منقضی شده است")
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


@router.get("/requests/{request_id}/messages")
async def request_messages(
    request_id: int,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """پیام‌های چتِ یک درخواست جلسه — فقط برای طرفین درخواست (دانش‌آموز/والد و معلم)."""
    req = await db.get(TutorRequest, request_id)
    if req is None or current.id not in (req.student_user_id, req.tutor_user_id):
        raise HTTPException(404, "درخواست یافت نشد")
    rows = (
        await db.execute(
            select(TutorMessage)
            .where(TutorMessage.request_id == request_id)
            .order_by(TutorMessage.id)
        )
    ).scalars().all()
    users = {u.id: u.full_name for u in (await db.execute(select(User))).scalars()}
    return {
        "request": {"id": req.id, "status": req.status, "subject": req.subject},
        "messages": [
            {
                "id": m.id,
                "sender": users.get(m.sender_user_id),
                "sender_id": m.sender_user_id,
                "content": m.content,
                "flagged": bool(m.flagged),
                "created_at": m.created_at,
            }
            for m in rows
        ],
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


# ---------------- §10.2: تأیید صالحیت، رضایت والد، کارت جلسه، کد دعوت ----------------


@router.get("/verification")
async def my_verification(
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """وضعیت فرم صالحیت خودِ معلم (§10.2-۲)."""
    if current.system_role != "teacher":
        raise HTTPException(403, "فقط معلم می‌تواند وضعیت صالحیت ببیند")
    ver = await tutoring_svc.get_verification(db, current.id)
    if ver is None:
        return {"status": "none", "status_fa": "هنوز فرمی ثبت نکرده‌اید"}
    return {
        "id": ver.id,
        "status": ver.status,
        "status_fa": tutoring_svc.VERIFICATION_STATUS_FA.get(ver.status, ver.status),
        "review_note": ver.review_note,
        "submitted_at": ver.submitted_at,
        "full_name": ver.full_name,
        "national_id_masked": ver.national_id_masked,
        "degree": ver.degree,
        "university": ver.university,
        "experience_years": ver.experience_years,
        "intro": ver.intro,
        "accepts_under18": bool(ver.accepts_under18),
        "police_clearance": bool(ver.police_clearance),
        "missing_fa": [
            fa
            for fa, ok in (
                ("نام و نام خانوادگی", bool(ver.full_name)),
                ("کد ملی", bool(ver.national_id_hash)),
                ("مدرک و رشته", bool(ver.degree)),
                ("معرفی", bool(ver.intro)),
            )
            if not ok
        ],
    }


class VerificationIn(BaseModel):
    full_name: str | None = None
    national_id: str | None = None
    degree: str | None = None
    university: str | None = None
    teaching_certificate: str | None = None
    experience_years: int | None = None
    intro: str | None = None
    expertise_topics: list[int] | None = None
    accepts_under18: bool | None = None
    police_clearance: bool | None = None


@router.post("/verification")
async def submit_verification(
    body: VerificationIn,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current.system_role != "teacher":
        raise HTTPException(403, "فقط معلم می‌تواند فرم صالحیت ثبت کند")
    result = await tutoring_svc.submit_verification(db, current.id, body.model_dump())
    if not result.get("ok"):
        raise HTTPException(400, result.get("reason"))
    await db.commit()
    return result


@router.get("/verifications/pending")
async def verification_queue(
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """صف بررسی مدارک — فقط نقش‌های نظارتی (§10.2-س)."""
    if current.system_role not in _VERIFIER_ROLES:
        raise HTTPException(403, "دسترسی نظارتی لازم است")
    return {"verifications": await tutoring_svc.pending_verifications(db)}


class VerificationDecisionIn(BaseModel):
    decision: str
    note: str | None = None


@router.post("/verifications/{verification_id}/decide")
async def decide_verification(
    verification_id: int,
    body: VerificationDecisionIn,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current.system_role not in _VERIFIER_ROLES:
        raise HTTPException(403, "دسترسی نظارتی لازم است")
    result = await tutoring_svc.decide_verification(
        db,
        verification_id=verification_id,
        reviewer_user_id=current.id,
        decision=body.decision,
        note=body.note,
    )
    if not result.get("ok"):
        raise HTTPException(400, result.get("reason"))
    await db.commit()
    return result


# ---------------- رضایت والد (§10.2-۵) ----------------


@router.get("/consents")
async def consents(
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current.system_role != "parent":
        raise HTTPException(403, "فقط والد می‌تواند درخواست رضایت ببیند")
    return {"consents": await tutoring_svc.pending_consents(db, current.id)}


class ConsentIn(BaseModel):
    approve: bool
    note: str | None = None


@router.post("/requests/{request_id}/consent")
async def consent_decision(
    request_id: int,
    body: ConsentIn,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current.system_role != "parent":
        raise HTTPException(403, "فقط والد می‌تواند رضایت دهد")
    result = await tutoring_svc.decide_consent(
        db,
        request_id=request_id,
        parent_user_id=current.id,
        approve=body.approve,
        note=body.note,
    )
    if not result.get("ok"):
        raise HTTPException(400, result.get("reason"))
    await db.commit()
    return result


# ---------------- کارت جلسه، حضور، امتیاز (§10.2-۸/۹) ----------------


class SessionIn(BaseModel):
    group_id: int | None = None
    student_user_id: int | None = None
    request_id: int | None = None
    starts_at: str
    duration_min: int = 60
    topic: str
    join_link: str | None = None


@router.post("/sessions")
async def create_session(
    body: SessionIn,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current.system_role != "teacher":
        raise HTTPException(403, "فقط معلم می‌تواند کارت جلسه ثبت کند")
    payload = body.model_dump()
    try:
        starts = datetime.fromisoformat(str(payload["starts_at"]).replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, "تاریخ شروع نامعتبر است")
    if starts.tzinfo is not None:
        from datetime import timezone as _tz

        starts = starts.astimezone(_tz.utc).replace(tzinfo=None)
    payload["starts_at"] = starts
    result = await tutoring_svc.create_session(
        db, actor_user_id=current.id, payload=payload
    )
    if not result.get("ok"):
        raise HTTPException(400, result.get("reason"))
    await db.commit()
    return result


@router.get("/sessions")
async def sessions(
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    role = current.system_role if current.system_role in ("student", "parent", "teacher") else "student"
    return {"sessions": await tutoring_svc.list_sessions(db, user_id=current.id, role=role)}


@router.post("/sessions/{session_id}/attend")
async def attend_session(
    session_id: int,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await tutoring_svc.attend_session(
        db, session_id=session_id, student_user_id=current.id
    )
    if not result.get("ok"):
        raise HTTPException(400, result.get("reason"))
    await db.commit()
    return result


@router.post("/sessions/{session_id}/confirm")
async def confirm_session(
    session_id: int,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current.system_role != "teacher":
        raise HTTPException(403, "فقط معلم می‌تواند جلسه را تأیید کند")
    result = await tutoring_svc.confirm_session(
        db, session_id=session_id, tutor_user_id=current.id
    )
    if not result.get("ok"):
        raise HTTPException(400, result.get("reason"))
    await db.commit()
    return result


class SessionNoteIn(BaseModel):
    note: str | None = None
    homework: str | None = None


@router.post("/sessions/{session_id}/note")
async def session_note(
    session_id: int,
    body: SessionNoteIn,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current.system_role != "teacher":
        raise HTTPException(403, "فقط معلم می‌تواند یادداشت ثبت کند")
    result = await tutoring_svc.save_session_note(
        db, session_id=session_id, tutor_user_id=current.id, note=body.note, homework=body.homework
    )
    if not result.get("ok"):
        raise HTTPException(400, result.get("reason"))
    await db.commit()
    return result


class FeedbackIn(BaseModel):
    rating: int
    comment: str | None = None


@router.post("/sessions/{session_id}/feedback")
async def session_feedback(
    session_id: int,
    body: FeedbackIn,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    role = current.system_role if current.system_role in ("student", "parent") else None
    if role is None:
        raise HTTPException(403, "فقط دانش‌آموز یا والد می‌تواند امتیاز دهد")
    result = await tutoring_svc.add_feedback(
        db,
        session_id=session_id,
        from_user_id=current.id,
        from_role=role,
        rating=body.rating,
        comment=body.comment,
    )
    if not result.get("ok"):
        raise HTTPException(400, result.get("reason"))
    await db.commit()
    return result


# ---------------- کد دعوت امن (§10.2-۵) ----------------


@router.post("/groups/{group_id}/invites")
async def make_invite(
    group_id: int,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await tutoring_svc.create_invite(
        db, group_id=group_id, creator_user_id=current.id
    )
    if not result.get("ok"):
        raise HTTPException(400, result.get("reason"))
    await db.commit()
    return result


class InviteIn(BaseModel):
    code: str


@router.post("/invites/join")
async def join_with_invite(
    body: InviteIn,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await tutoring_svc.join_by_invite(
        db, code=body.code, student_user_id=current.id
    )
    if not result.get("ok"):
        raise HTTPException(400, result.get("reason"))
    await db.commit()
    return result
