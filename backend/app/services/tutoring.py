"""Private-tutor marketplace service (roadmap phase 8 «معلم خصوصی»).

ایمنی زیر ۱۸ (سند): فیلتر شماره تماس/پیوند خارجی در پیام‌ها، گزارش کاربر،
ثبت ممیزی؛ چت گروهی فقط بین معلم و اعضای گروهش."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.org import ParentLink, User
from app.models.rbac import AuditLog
from app.models.slm import StudentTopicState
from app.models.tutoring import (
    ParentConsent,
    TutorFeedback,
    TutorGroup,
    TutorGroupMember,
    TutorInvite,
    TutorMessage,
    TutorProfile,
    TutorRequest,
    TutorSession,
    TutorVerification,
)

# مهلت پاسخ معلم به درخواست (سند §10.2-۶: اگر در ۷۲ ساعت پاسخ ندهد، درخواست منقضی می‌شود)
REQUEST_TTL_HOURS = 72
# سقف اعضای گروه کلاس خصوصی (سند §10.2-۵: پیش‌فرض ۶ نفر)
GROUP_MEMBER_CAP = 6
# سرویس‌های مجاز برای لینک کلاس آنلاین (سند §10.2-د)
_ALLOWED_LINK_RE = re.compile(
    r"https?://(?:[a-z0-9-]+\.)*(?:meet\.google\.com|zoom\.us|zoomgov\.com|teams\.microsoft\.com|teams\.live\.com)\S*",
    re.IGNORECASE,
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
    """حذف/-mask اطلاعات تماس شخصی از پیام. Returns (clean_text, flagged).

    لینک سرویس‌های مجاز کلاس آنلاین (Meet/Zoom/Teams) حفظ می‌شود — فقط پیوندِ
    خارجیِ غیرمجاز حذف می‌شود (سند §10.2-د)."""
    # لینک‌های مجاز را موقتاً نگه می‌داریم تا فیلتر آن‌ها را نزند
    kept: list[str] = []

    def _park(m: re.Match) -> str:
        kept.append(m.group(0))
        return f"\x00LINK{len(kept) - 1}\x00"

    staged = _ALLOWED_LINK_RE.sub(_park, text)

    flagged = False
    out = _PHONE_RE.sub("[شماره تماس حذف شد]", staged)
    flagged = flagged or out != staged
    out2 = _LINK_RE.sub("[پیوند خارجی حذف شد]", out)
    flagged = flagged or out2 != out
    out3 = _EMAIL_RE.sub("[ایمیل حذف شد]", out2)
    flagged = flagged or out3 != out2
    for i, link in enumerate(kept):
        out3 = out3.replace(f"\x00LINK{i}\x00", link)
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


async def market_list(
    db: AsyncSession,
    subject: str | None = None,
    viewer_user_id: int | None = None,
    viewer_role: str | None = None,
) -> dict:
    """بازار معلم‌ها: نمایه‌های فعال + نشان «تأییدشده» + امتیاز تجمیعی + پیشنهاد هوشمند (§10.2)."""
    profiles = (await db.execute(select(TutorProfile).where(TutorProfile.is_active.is_(True)))).scalars().all()
    users = {u.id: u for u in (await db.execute(select(User))).scalars()}
    verifications = {v.profile_id: v for v in (await db.execute(select(TutorVerification))).scalars()}

    # میانگین امتیاز جلسات (تجمیعی — بدون نمایش هویت امتیازدهنده، §10.2-۹)
    sessions = {s.id: s for s in (await db.execute(select(TutorSession))).scalars()}
    ratings_by_tutor: dict[int, list[int]] = {}
    for fb in (await db.execute(select(TutorFeedback))).scalars():
        sess = sessions.get(fb.session_id)
        if sess is not None:
            ratings_by_tutor.setdefault(sess.tutor_user_id, []).append(fb.rating)

    # ضعیف‌ترین مباحث دانش‌آموز برای تطبیق هوشمند
    weak_topics: dict[int, float] = {}
    if viewer_user_id is not None and viewer_role == "student":
        settings = get_settings()
        states = (
            await db.execute(
                select(StudentTopicState).where(StudentTopicState.student_user_id == viewer_user_id)
            )
        ).scalars().all()
        for st in states:
            if st.evidence_count < 1 or st.effective_mastery >= settings.threshold_consolidating:
                continue
            severity = (settings.threshold_consolidating - st.effective_mastery) / max(
                settings.threshold_consolidating, 1
            )
            weak_topics[st.topic_id] = max(weak_topics.get(st.topic_id, 0.0), round(severity, 3))

    rows = []
    for p in profiles:
        if subject and subject not in (p.subjects or []):
            continue
        u = users.get(p.user_id)
        ver = verifications.get(p.id)
        verified = bool(ver and ver.status == "verified")
        ratings = ratings_by_tutor.get(p.user_id, [])
        rating_avg = round(sum(ratings) / len(ratings), 2) if ratings else None

        match_score: float | None = None
        if weak_topics:
            expertise = [int(t) for t in ((ver.expertise_topics if ver else None) or [])]
            sev_sum = 0.0
            weighted = 0.0
            for tid, sev in weak_topics.items():
                sev_sum += sev
                # بدون فهرست تخصص → معلم «کلی» فرض می‌شود (۰٫۵)
                exp = (1.0 if tid in expertise else 0.0) if expertise else 0.5
                weighted += sev * exp
            severity_match = (weighted / sev_sum) if sev_sum > 0 else 0.0
            rating_norm = (sum(ratings) / len(ratings) / 5.0) if ratings else 0.5
            availability_overlap = 1.0 if p.availability else 0.0
            match_score = round(severity_match * 0.6 + rating_norm * 0.25 + availability_overlap * 0.15, 3)

        rows.append(
            {
                "profile_id": p.id,
                "user_id": p.user_id,
                "name": u.full_name if u else f"#{p.user_id}",
                "headline": p.headline,
                "subjects": p.subjects,
                "session_price": p.session_price,
                "availability": p.availability,
                "verified": verified,
                "verification_status": ver.status if ver else "none",
                "rating_avg": rating_avg,
                "rating_count": len(ratings),
                "match_score": match_score,
            }
        )
    if weak_topics:
        rows.sort(key=lambda r: (r["match_score"] is None, -(r["match_score"] or 0)))
    return {
        "tutors": rows,
        "weak_topics": [{"topic_id": k, "severity": v} for k, v in sorted(weak_topics.items())],
        "match_note_fa": (
            "ترتیب از «پیشنهاد هوشمند» می‌آید: تناسب ضعف‌های تو با تخصص معلم ۶۰٪، امتیاز ۲۵٪ و ساعت آزاد ۱۵٪ (§10.2-ب)."
            if weak_topics
            else "برای فعال شدن پیشنهاد هوشمند، ابتدا شواهد یادگیری‌ات ثبت می‌شود."
        ),
    }


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


async def _member_count(db: AsyncSession, group_id: int) -> int:
    rows = (
        await db.execute(select(TutorGroupMember).where(TutorGroupMember.group_id == group_id))
    ).scalars().all()
    return len(rows)


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
    if await _member_count(db, group_id) >= GROUP_MEMBER_CAP:
        return {"ok": False, "reason": f"سقف اعضای گروه ({GROUP_MEMBER_CAP} نفر) پر شده است"}
    db.add(TutorGroupMember(group_id=group_id, student_user_id=student_user_id))
    await db.flush()
    return {"ok": True, "already": False}


# ---------------- §10.2: تأیید صالحیت، رضایت والد، ۷۲ ساعت، کارت جلسه ----------------


def _now_naive() -> datetime:
    return datetime.utcnow()


def request_expires_at(req: TutorRequest) -> datetime:
    created = req.created_at.replace(tzinfo=None) if req.created_at.tzinfo else req.created_at
    return created + timedelta(hours=REQUEST_TTL_HOURS)


def is_expired(req: TutorRequest) -> bool:
    """مهلت ۷۲ ساعتهٔ پاسخ معلم (§10.2-۶)."""
    return req.status == "pending" and _now_naive() > request_expires_at(req)


def hash_national_id(national_id: str) -> str:
    """کد ملی فقط به‌صورت هش‌شده با کلید سراسری ذخیره می‌شود (§18)."""
    key = get_settings().secret_key.encode()
    return hashlib.sha256(key + national_id.strip().encode()).hexdigest()


async def get_verification(db: AsyncSession, tutor_user_id: int) -> TutorVerification | None:
    prof = (
        await db.execute(select(TutorProfile).where(TutorProfile.user_id == tutor_user_id))
    ).scalar_one_or_none()
    if prof is None:
        return None
    return (
        await db.execute(select(TutorVerification).where(TutorVerification.profile_id == prof.id))
    ).scalar_one_or_none()


VERIFICATION_STATUS_FA = {
    "draft": "پیش‌نویس",
    "submitted": "ارسال‌شده",
    "in_review": "در بررسی",
    "verified": "تأییدشده",
    "rejected": "ردشده",
    "needs_completion": "نیازمند تکمیل",
    "suspended": "تعلیق‌شده",
}


async def submit_verification(db: AsyncSession, tutor_user_id: int, payload: dict) -> dict:
    """ثبت/به‌روزرسانی فرم صالحیت و ارسال برای بررسی (§10.2-۲)."""
    prof = (
        await db.execute(select(TutorProfile).where(TutorProfile.user_id == tutor_user_id))
    ).scalar_one_or_none()
    if prof is None:
        return {"ok": False, "reason": "ابتدا نمایهٔ معلم خصوصی خود را بسازید"}
    ver = (
        await db.execute(select(TutorVerification).where(TutorVerification.profile_id == prof.id))
    ).scalar_one_or_none()
    if ver is None:
        ver = TutorVerification(profile_id=prof.id)
        db.add(ver)
    if ver.status in ("verified", "in_review"):
        return {"ok": False, "reason": "درخواست شما در حال بررسی است؛ تا اعلام نتیجه قابل ویرایش نیست"}
    ver.full_name = payload.get("full_name") or ver.full_name
    nid = payload.get("national_id")
    if nid:
        ver.national_id_hash = hash_national_id(nid)
        ver.national_id_masked = "***" + nid.strip()[-3:]
    ver.degree = payload.get("degree") or ver.degree
    ver.university = payload.get("university") or ver.university
    ver.teaching_certificate = payload.get("teaching_certificate") or ver.teaching_certificate
    ver.experience_years = payload.get("experience_years", ver.experience_years)
    ver.intro = payload.get("intro") or ver.intro
    if payload.get("expertise_topics") is not None:
        ver.expertise_topics = [int(t) for t in payload["expertise_topics"]]
    if payload.get("accepts_under18") is not None:
        ver.accepts_under18 = bool(payload["accepts_under18"])
    if payload.get("police_clearance") is not None:
        ver.police_clearance = 1 if payload["police_clearance"] else 0
    missing = [
        fa
        for fa, ok in (
            ("نام و نام خانوادگی", bool(ver.full_name)),
            ("کد ملی", bool(ver.national_id_hash)),
            ("مدرک و رشته", bool(ver.degree)),
            ("معرفی", bool(ver.intro)),
        )
        if not ok
    ]
    if missing:
        ver.status = "draft"
        await db.flush()
        return {"ok": False, "reason": "برای ارسال، این موارد لازم است: " + "، ".join(missing)}
    ver.status = "submitted"
    ver.submitted_at = _now_naive()
    await db.flush()
    await _log(
        db,
        tutor_user_id,
        "tutor_verification_submitted",
        "tutor_verification",
        ver.id,
        "فرم تأیید صالحیت برای بررسی ارسال شد",
    )
    return {"ok": True, "status": ver.status, "status_fa": VERIFICATION_STATUS_FA.get(ver.status)}


async def decide_verification(
    db: AsyncSession, *, verification_id: int, reviewer_user_id: int, decision: str, note: str | None
) -> dict:
    """بررسی مدارک توسط دانشیار: verified | rejected | needs_completion | suspended (§10.2-س)."""
    if decision not in ("verified", "rejected", "needs_completion", "suspended", "in_review"):
        return {"ok": False, "reason": "وضعیت نامعتبر است"}
    ver = await db.get(TutorVerification, verification_id)
    if ver is None:
        return {"ok": False, "reason": "درخواستی یافت نشد"}
    ver.status = decision
    ver.review_note = note
    ver.decided_by = reviewer_user_id
    ver.decided_at = _now_naive()
    await db.flush()
    await _log(
        db,
        reviewer_user_id,
        f"tutor_verification_{decision}",
        "tutor_verification",
        ver.id,
        (note or VERIFICATION_STATUS_FA.get(decision, decision))[:250],
    )
    return {"ok": True, "status": ver.status, "status_fa": VERIFICATION_STATUS_FA.get(decision)}


async def pending_verifications(db: AsyncSession) -> list[dict]:
    rows = (
        await db.execute(
            select(TutorVerification).where(TutorVerification.status.in_(["submitted", "in_review"]))
        )
    ).scalars().all()
    users = {u.id: u for u in (await db.execute(select(User))).scalars()}
    profiles = {p.id: p for p in (await db.execute(select(TutorProfile))).scalars()}
    out = []
    for v in rows:
        prof = profiles.get(v.profile_id)
        out.append(
            {
                "id": v.id,
                "tutor_name": users.get(prof.user_id).full_name if prof and users.get(prof.user_id) else None,
                "status": v.status,
                "degree": v.degree,
                "university": v.university,
                "experience_years": v.experience_years,
                "submitted_at": v.submitted_at,
                "accepts_under18": v.accepts_under18,
            }
        )
    return out


# ---------------- رضایت والد (§10.2-۵) ----------------


async def student_parent_ids(db: AsyncSession, student_user_id: int) -> list[int]:
    links = (
        await db.execute(
            select(ParentLink).where(
                ParentLink.student_user_id == student_user_id,
                ParentLink.status == "active",
            )
        )
    ).scalars().all()
    return [l.parent_user_id for l in links]


async def create_request(
    db: AsyncSession, *, student_user_id: int, tutor_user_id: int, subject: str, note: str | None
) -> dict:
    """درخواست کلاس؛ برای دانش‌آموز زیر ۱۸ (دارای والد متصل) ابتدا رضایت والد گرفته می‌شود
    و بدون تأیید او، درخواست به معلم نمی‌رسد (§10.2-۵)."""
    prof = (
        await db.execute(select(TutorProfile).where(TutorProfile.user_id == tutor_user_id))
    ).scalar_one_or_none()
    ver = None
    if prof is not None:
        ver = (
            await db.execute(select(TutorVerification).where(TutorVerification.profile_id == prof.id))
        ).scalar_one_or_none()
    if ver is not None and ver.status in ("rejected", "suspended"):
        return {"ok": False, "reason": "این معلم برای پذیرش شاگرد تأیید نشده است"}

    req = TutorRequest(
        student_user_id=student_user_id,
        tutor_user_id=tutor_user_id,
        subject=subject,
        note=note,
    )
    db.add(req)
    await db.flush()

    parents = await student_parent_ids(db, student_user_id)
    consent = None
    if parents:
        consent = ParentConsent(request_id=req.id, parent_user_id=parents[0])
        db.add(consent)
        await db.flush()
    await _log(
        db,
        student_user_id,
        "tutor_request_created",
        "tutor_request",
        req.id,
        "درخواست کلاس خصوصی ثبت شد" + ("؛ در انتظار رضایت والد" if parents else ""),
    )
    return {
        "ok": True,
        "request_id": req.id,
        "status": req.status,
        "requires_parent_consent": bool(parents),
        "expires_at": request_expires_at(req),
        "note_fa": (
            "برای زیر ۱۸ سال، پیام تأیید به والد رفت؛ بدون تأیید او درخواست به معلم نمی‌رسد (§10.2)."
            if parents
            else f"معلم {REQUEST_TTL_HOURS} ساعت فرصت پاسخ دارد؛ در غیر این صورت درخواست منقضی می‌شود."
        ),
    }


async def request_state(req: TutorRequest, consent: ParentConsent | None) -> dict:
    """وضعیت خوانا برای رابط: منقضی/در انتظار والد/آمادهٔ پاسخ."""
    if consent is not None and consent.status == "pending":
        state = "awaiting_parent"
        state_fa = "در انتظار تأیید والد"
    elif consent is not None and consent.status == "rejected":
        state = "rejected_by_parent"
        state_fa = "والد رد کرد"
    elif is_expired(req):
        state = "expired"
        state_fa = "منقضی شده (۷۲ ساعت گذشته)"
    else:
        state = req.status
        state_fa = {
            "pending": "در انتظار پاسخ معلم",
            "accepted": "پذیرفته شد",
            "rejected": "رد شد",
        }.get(req.status, req.status)
    return {
        "state": state,
        "state_fa": state_fa,
        "expires_at": request_expires_at(req),
        "hours_left": max(
            0, int((request_expires_at(req) - _now_naive()).total_seconds() // 3600)
        ),
        "visible_to_tutor": consent is None or consent.status == "approved",
    }


async def get_consent(db: AsyncSession, request_id: int) -> ParentConsent | None:
    return (
        await db.execute(select(ParentConsent).where(ParentConsent.request_id == request_id))
    ).scalar_one_or_none()


async def decide_consent(
    db: AsyncSession, *, request_id: int, parent_user_id: int, approve: bool, note: str | None
) -> dict:
    consent = await get_consent(db, request_id)
    if consent is None:
        return {"ok": False, "reason": "درخواستی برای تأیید والد وجود ندارد"}
    if consent.parent_user_id != parent_user_id:
        return {"ok": False, "reason": "شما والد این دانش‌آموز نیستید"}
    if consent.status != "pending":
        return {"ok": False, "reason": "این درخواست قبلاً تصمیم گرفته شده است"}
    consent.status = "approved" if approve else "rejected"
    consent.note = note
    consent.decided_at = datetime.now(timezone.utc)
    await db.flush()
    await _log(
        db,
        parent_user_id,
        "tutor_parent_consent",
        "tutor_request",
        request_id,
        "رضایت والد " + ("تأیید شد" if approve else "رد شد"),
    )
    return {"ok": True, "status": consent.status}


async def pending_consents(db: AsyncSession, parent_user_id: int) -> list[dict]:
    rows = (
        await db.execute(
            select(ParentConsent).where(
                ParentConsent.parent_user_id == parent_user_id,
                ParentConsent.status == "pending",
            )
        )
    ).scalars().all()
    out = []
    for c in rows:
        req = await db.get(TutorRequest, c.request_id)
        if req is None:
            continue
        users = {u.id: u.full_name for u in (await db.execute(select(User))).scalars()}
        out.append(
            {
                "request_id": req.id,
                "tutor_name": users.get(req.tutor_user_id),
                "student_name": users.get(req.student_user_id),
                "subject": req.subject,
                "note": req.note,
                "created_at": req.created_at,
                "status": c.status,
            }
        )
    return out


# ---------------- کارت جلسه، حضور، امتیاز (§10.2-۸/۹) ----------------


async def create_session(db: AsyncSession, *, actor_user_id: int, payload: dict) -> dict:
    """معلم برای هر جلسه تاریخ، ساعت، موضوع و لینک را ثبت می‌کند (§10.2-۸)."""
    group_id = payload.get("group_id")
    student_user_id = payload.get("student_user_id")
    if group_id is not None:
        group = await db.get(TutorGroup, group_id)
        if group is None or group.tutor_user_id != actor_user_id:
            return {"ok": False, "reason": "گروه یافت نشد یا متعلق به شما نیست"}
    if student_user_id is None:
        if group_id is None:
            return {"ok": False, "reason": "دانش‌آموز یا گروه را مشخص کنید"}
        member = (
            await db.execute(
                select(TutorGroupMember)
                .where(TutorGroupMember.group_id == group_id)
                .order_by(TutorGroupMember.id)
                .limit(1)
            )
        ).scalars().first()
        if member is None:
            return {"ok": False, "reason": "هنوز عضوی در گروه نیست"}
        student_user_id = member.student_user_id

    link = payload.get("join_link")
    if link and not _ALLOWED_LINK_RE.fullmatch(link.strip()):
        return {"ok": False, "reason": "لینک فقط باید از سرویس‌های مجاز کلاس آنلاین باشد (Meet/Zoom/Teams)"}

    session = TutorSession(
        tutor_user_id=actor_user_id,
        student_user_id=student_user_id,
        group_id=group_id,
        request_id=payload.get("request_id"),
        starts_at=payload["starts_at"],
        duration_min=int(payload.get("duration_min") or 60),
        topic=payload["topic"],
        join_link=link,
    )
    db.add(session)
    await db.flush()
    await _log(
        db, actor_user_id, "tutor_session_created", "tutor_session", session.id, "کارت جلسه ثبت شد"
    )
    return {"ok": True, "session_id": session.id}


async def attend_session(db: AsyncSession, *, session_id: int, student_user_id: int) -> dict:
    """دانش‌آموز با «ورود به کلاس» حضورش ثبت می‌شود (§10.2-۸)."""
    s = await db.get(TutorSession, session_id)
    if s is None or s.student_user_id != student_user_id:
        return {"ok": False, "reason": "جلسه یافت نشد"}
    if s.status == "cancelled":
        return {"ok": False, "reason": "این جلسه لغو شده است"}
    if s.attended_at is None:
        s.attended_at = datetime.now(timezone.utc)
        await db.flush()
        await _log(
            db, student_user_id, "tutor_session_attended", "tutor_session", session_id, "حضور در جلسه ثبت شد"
        )
    return {"ok": True, "attended_at": s.attended_at}


async def confirm_session(db: AsyncSession, *, session_id: int, tutor_user_id: int) -> dict:
    """معلم در پایان حضور را تأیید و جلسه را کامل می‌کند (§10.2-۸)."""
    s = await db.get(TutorSession, session_id)
    if s is None or s.tutor_user_id != tutor_user_id:
        return {"ok": False, "reason": "جلسه یافت نشد"}
    s.tutor_confirmed = 1
    s.status = "completed"
    if s.attended_at is None:
        s.attended_at = datetime.now(timezone.utc)
    await db.flush()
    await _log(
        db, tutor_user_id, "tutor_session_confirmed", "tutor_session", session_id, "حضور توسط معلم تأیید شد"
    )
    return {"ok": True, "status": s.status}


async def save_session_note(
    db: AsyncSession, *, session_id: int, tutor_user_id: int, note: str | None, homework: str | None
) -> dict:
    """یادداشت جلسه و تکلیف → وارد برنامهٔ دانش‌آموز و گزارش والدین می‌شود (§10.2-۹)."""
    s = await db.get(TutorSession, session_id)
    if s is None or s.tutor_user_id != tutor_user_id:
        return {"ok": False, "reason": "جلسه یافت نشد"}
    s.lesson_note = note
    s.homework = homework
    await db.flush()
    return {"ok": True}


async def add_feedback(
    db: AsyncSession,
    *,
    session_id: int,
    from_user_id: int,
    from_role: str,
    rating: int,
    comment: str | None,
) -> dict:
    """امتیاز و بازخورد دانش‌آموز/والد پایان جلسه — تجمیعی نمایش داده می‌شود (§10.2-۹)."""
    if from_role not in ("student", "parent"):
        return {"ok": False, "reason": "نقش نامعتبر است"}
    if not (1 <= int(rating) <= 5):
        return {"ok": False, "reason": "امتیاز باید بین ۱ تا ۵ باشد"}
    s = await db.get(TutorSession, session_id)
    if s is None:
        return {"ok": False, "reason": "جلسه یافت نشد"}
    if from_role == "student" and s.student_user_id != from_user_id:
        return {"ok": False, "reason": "جلسه‌ای برای شما ثبت نشده"}
    if from_role == "parent":
        parents = await student_parent_ids(db, s.student_user_id)
        if from_user_id not in parents:
            return {"ok": False, "reason": "شما والد این دانش‌آموز نیستید"}
    existing = (
        await db.execute(
            select(TutorFeedback).where(
                TutorFeedback.session_id == session_id, TutorFeedback.from_user_id == from_user_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.rating = int(rating)
        existing.comment = comment
    else:
        db.add(
            TutorFeedback(
                session_id=session_id,
                from_user_id=from_user_id,
                from_role=from_role,
                rating=int(rating),
                comment=comment,
            )
        )
    await db.flush()
    return {"ok": True}


async def list_sessions(db: AsyncSession, *, user_id: int, role: str) -> list[dict]:
    rows = (
        await db.execute(
            select(TutorSession)
            .where(
                (TutorSession.tutor_user_id == user_id)
                | (TutorSession.student_user_id == user_id)
                | (TutorSession.group_id.in_(select(TutorGroupMember.group_id).where(
                    TutorGroupMember.student_user_id == user_id
                )))
            )
            .order_by(TutorSession.starts_at.desc())
        )
    ).scalars().all()
    if role == "parent":
        children = await student_parent_ids(db, user_id)
        # والد جلسات فرزندان متصلش را می‌بیند
        rows = [s for s in rows if s.student_user_id in children or s.student_user_id == user_id]
    users = {u.id: u.full_name for u in (await db.execute(select(User))).scalars()}
    feedback = (await db.execute(select(TutorFeedback))).scalars().all()
    out = []
    for s in rows:
        mine = [f for f in feedback if f.session_id == s.id]
        out.append(
            {
                "id": s.id,
                "topic": s.topic,
                "starts_at": s.starts_at,
                "duration_min": s.duration_min,
                "join_link": s.join_link,
                "status": s.status,
                "tutor_name": users.get(s.tutor_user_id),
                "student_name": users.get(s.student_user_id),
                "attended": s.attended_at is not None,
                "tutor_confirmed": bool(s.tutor_confirmed),
                "lesson_note": s.lesson_note,
                "homework": s.homework,
                "rating": next(
                    (f.rating for f in mine if f.from_user_id == user_id), None
                ),
                "rating_avg": round(sum(f.rating for f in mine) / len(mine), 2) if mine else None,
            }
        )
    return out


# ---------------- کد دعوت امن (§10.2-۵ پیشنهاد اصلاحی) ----------------


def _invite_code() -> str:
    import secrets

    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(6))


async def create_invite(db: AsyncSession, *, group_id: int, creator_user_id: int) -> dict:
    group = await db.get(TutorGroup, group_id)
    if group is None or group.tutor_user_id != creator_user_id:
        return {"ok": False, "reason": "گروه یافت نشد یا متعلق به شما نیست"}
    invite = TutorInvite(
        group_id=group_id,
        code=_invite_code(),
        created_by=creator_user_id,
        expires_at=_now_naive() + timedelta(days=7),
    )
    db.add(invite)
    await db.flush()
    await _log(
        db, creator_user_id, "tutor_invite_created", "tutor_group", group_id, "کد دعوت گروه ساخته شد"
    )
    return {"ok": True, "code": invite.code, "expires_at": invite.expires_at}


async def join_by_invite(db: AsyncSession, *, code: str, student_user_id: int) -> dict:
    """عضویت فقط با کد دعوت — بدون جست‌وجوی کد ملی و بدون افشای نتیجهٔ جست‌وجو (§10.2-۵)."""
    invite = (
        await db.execute(select(TutorInvite).where(TutorInvite.code == code.strip().upper()))
    ).scalar_one_or_none()
    if invite is None:
        return {"ok": False, "reason": "کد دعوت معتبر نیست"}
    if invite.expires_at is not None and _now_naive() > invite.expires_at:
        return {"ok": False, "reason": "کد دعوت منقضی شده است"}
    return await join_group(db, group_id=invite.group_id, student_user_id=student_user_id)
