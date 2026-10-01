"""Private-tutor marketplace service (roadmap phase 8 «معلم خصوصی»).

ایمنی زیر ۱۸ (سند): فیلتر شماره تماس/پیوند خارجی در پیام‌ها، گزارش کاربر،
ثبت ممیزی؛ چت گروهی فقط بین معلم و اعضای گروهش."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.org import User
from app.models.rbac import AuditLog
from app.models.tutoring import (
    TutorGroup,
    TutorGroupMember,
    TutorMessage,
    TutorProfile,
    TutorRequest,
)

# الگوهای ایمنی: شماره ایران، پیوند/دامنه خارجی، ایمیل، آیدی شبکه اجتماعی
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?98|0)?9\d{9}(?!\d)")
_LINK_RE = re.compile(
    r"https?://\S+|t\.me/\S+|instagram\.com/\S+|@\w{4,}|"
    r"\b(?:[a-z0-9-]+\.)+(?:com|net|org|ir|io|me|edu|co)(?:/\S*)?",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")


def safety_filter(text: str) -> tuple[str, bool]:
    """حذف/-mask اطلاعات تماس شخصی از پیام. Returns (clean_text, flagged)."""
    flagged = False
    out = _PHONE_RE.sub("[شماره تماس حذف شد]", text)
    flagged = flagged or out != text
    out2 = _LINK_RE.sub("[پیوند خارجی حذف شد]", out)
    flagged = flagged or out2 != out
    out3 = _EMAIL_RE.sub("[ایمیل حذف شد]", out2)
    flagged = flagged or out3 != out2
    return out3, flagged


async def _log(db: AsyncSession, actor: int, action: str, entity_type: str, entity_id: int, detail: str) -> None:
    db.add(
        AuditLog(
            actor_user_id=actor,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            detail=detail,
            created_at=datetime.now(timezone.utc),
        )
    )
    await db.flush()


async def market_list(db: AsyncSession, subject: str | None = None) -> dict:
    """بازار معلم‌ها: نمایه‌های فعال."""
    profiles = (await db.execute(select(TutorProfile).where(TutorProfile.is_active.is_(True)))).scalars().all()
    users = {u.id: u for u in (await db.execute(select(User))).scalars()}
    rows = []
    for p in profiles:
        if subject and subject not in (p.subjects or []):
            continue
        u = users.get(p.user_id)
        rows.append(
            {
                "profile_id": p.id,
                "user_id": p.user_id,
                "name": u.full_name if u else f"#{p.user_id}",
                "headline": p.headline,
                "subjects": p.subjects,
                "session_price": p.session_price,
                "availability": p.availability,
            }
        )
    return {"tutors": rows}


async def send_message(
    db: AsyncSession, *, sender_user_id: int, content: str, group_id: int | None, request_id: int | None
) -> dict:
    """ارسال پیام با فیلتر ایمنی + کنترل عضویت گروه."""
    if group_id is not None:
        group = await db.get(TutorGroup, group_id)
        if group is None:
            return {"ok": False, "reason": "گروه یافت نشد"}
        if group.tutor_user_id != sender_user_id:
            member = (
                await db.execute(
                    select(TutorGroupMember).where(
                        TutorGroupMember.group_id == group_id,
                        TutorGroupMember.student_user_id == sender_user_id,
                    )
                )
            ).scalar_one_or_none()
            if member is None:
                return {"ok": False, "reason": "شما عضو این گروه نیستید"}
    elif request_id is not None:
        req = await db.get(TutorRequest, request_id)
        if req is None or sender_user_id not in (req.student_user_id, req.tutor_user_id):
            return {"ok": False, "reason": "در این گفت‌وگو عضو نیستید"}
    else:
        return {"ok": False, "reason": "مقصد پیام مشخص نیست"}

    clean, flagged = safety_filter(content)
    msg = TutorMessage(
        group_id=group_id,
        request_id=request_id,
        sender_user_id=sender_user_id,
        content=clean,
        flagged=1 if flagged else 0,
    )
    db.add(msg)
    await db.flush()
    if flagged:
        await _log(
            db,
            sender_user_id,
            "tutor_message_filtered",
            "tutor_message",
            msg.id,
            "اطلاعات تماس/پیوند خارجی در پیام زیر ۱۸ فیلتر شد",
        )
    return {"ok": True, "message_id": msg.id, "content": clean, "flagged": flagged}


async def report_message(db: AsyncSession, *, reporter_user_id: int, message_id: int, reason: str) -> dict:
    """گزارش پیام → ثبت ممیزی (برای نظارت)."""
    msg = await db.get(TutorMessage, message_id)
    if msg is None:
        return {"ok": False, "reason": "پیام یافت نشد"}
    msg.report_reason = reason
    await _log(
        db,
        reporter_user_id,
        "tutor_message_reported",
        "tutor_message",
        message_id,
        reason[:250],
    )
    return {"ok": True}


async def join_group(db: AsyncSession, *, group_id: int, student_user_id: int) -> dict:
    group = await db.get(TutorGroup, group_id)
    if group is None or not group.is_open:
        return {"ok": False, "reason": "گروه یافت نشد یا بسته است"}
    existing = (
        await db.execute(
            select(TutorGroupMember).where(
                TutorGroupMember.group_id == group_id,
                TutorGroupMember.student_user_id == student_user_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return {"ok": True, "already": True}
    db.add(TutorGroupMember(group_id=group_id, student_user_id=student_user_id))
    await db.flush()
    return {"ok": True, "already": False}
