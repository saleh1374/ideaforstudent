"""سرویس بخش مالی (سند پنل والدین §18 + تصمیم باز §10.۲ سند دانش‌آموز).

همه‌ی نوشتن‌ها با flush/commit خودِ صداکننده انجام می‌شود (الگوی سرویس‌های
موجود)؛ اینجا فقط اعتبارسنجی، ثبت و تجمیع انجام می‌شود. پرداخت پیش‌فرض
«خارج از سیستم» است و هیچ منطق درگاه/تأیید پرداخت جعلی‌ای وجود ندارد."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing import (
    METHOD_FA,
    PACK_STATUS_FA,
    PAYMENT_STATUS_FA,
    REFUND_STATUS_FA,
    PaymentTransaction,
    RefundRequest,
    SessionPack,
)
from app.models.org import ParentLink, User


def payment_status_fa(status: str) -> str:
    """برچسب فارسی وضعیت پرداخت (پرداخت‌شده/در انتظار/ناموفق/بازپرداخت‌شده)."""
    return PAYMENT_STATUS_FA.get(status, status)


# یادداشت حالت پرداخت (§10.۲) — در همه پاسخ‌های مالی تکرار می‌شود
MODE_NOTE_FA = (
    "پرداخت فعلاً خارج از سیستم ثبت می‌شود (گزینه الف بخش ۱۰.۲)؛ "
    "امکان پرداخت داخلی با نگه‌داری امانی در نسخه‌های آینده."
)


async def _child_ids(db: AsyncSession, parent_id: int) -> list[int]:
    """شناسه‌ی فرزندان متصل‌شده‌ی فعال به این والد (§17 — فقط پیوند active)."""
    links = (
        await db.execute(
            select(ParentLink.student_user_id).where(
                ParentLink.parent_user_id == parent_id,
                ParentLink.status == "active",
            )
        )
    ).scalars().all()
    return list(links)


async def _user_names(db: AsyncSession, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    rows = (await db.execute(select(User.id, User.full_name).where(User.id.in_(ids)))).all()
    return {r[0]: r[1] for r in rows}


def _pack_row(pack: SessionPack, names: dict[int, str]) -> dict:
    """سریال‌سازی بسته جلسات — remaining محاسبه‌ای است، نه ذخیره‌شده."""
    return {
        "id": pack.id,
        "student_user_id": pack.student_user_id,
        "student_name": names.get(pack.student_user_id, f"#{pack.student_user_id}"),
        "tutor_user_id": pack.tutor_user_id,
        "tutor_name": names.get(pack.tutor_user_id, f"#{pack.tutor_user_id}"),
        "subject": pack.subject,
        "purchased": pack.total_sessions,
        "used": pack.used_sessions,
        "remaining": pack.remaining,
        "price_per_session": pack.price_per_session,
        "total_price": (pack.price_per_session * pack.total_sessions) if pack.price_per_session else None,
        "status": pack.status,
        "status_fa": PACK_STATUS_FA.get(pack.status, pack.status),
        "created_at": pack.created_at.isoformat() if pack.created_at else None,
    }


def _payment_row(pay: PaymentTransaction, names: dict[int, str]) -> dict:
    return {
        "id": pay.id,
        "invoice_no": pay.invoice_no,
        "amount": pay.amount,
        "method": pay.method,
        "method_fa": METHOD_FA.get(pay.method, pay.method),
        "status": pay.status,
        "status_fa": PAYMENT_STATUS_FA.get(pay.status, pay.status),
        "payer_user_id": pay.payer_user_id,
        "payer_name": names.get(pay.payer_user_id, f"#{pay.payer_user_id}"),
        "student_user_id": pay.student_user_id,
        "student_name": names.get(pay.student_user_id, f"#{pay.student_user_id}"),
        "tutor_user_id": pay.tutor_user_id,
        "tutor_name": names.get(pay.tutor_user_id, f"#{pay.tutor_user_id}"),
        "session_pack_id": pay.session_pack_id,
        "description": pay.description,
        "created_at": pay.created_at.isoformat() if pay.created_at else None,
        "paid_at": pay.paid_at.isoformat() if pay.paid_at else None,
    }


def _refund_row(rf: RefundRequest, payments: dict[int, PaymentTransaction]) -> dict:
    pay = payments.get(rf.payment_id)
    return {
        "id": rf.id,
        "payment_id": rf.payment_id,
        "invoice_no": pay.invoice_no if pay else None,
        "amount": pay.amount if pay else None,
        "reason": rf.reason,
        "status": rf.status,
        "status_fa": REFUND_STATUS_FA.get(rf.status, rf.status),
        "created_at": rf.created_at.isoformat() if rf.created_at else None,
        "decided_at": rf.decided_at.isoformat() if rf.decided_at else None,
        "decision_note": rf.decision_note,
    }


async def parent_overview(db: AsyncSession, parent_id: int) -> dict:
    """نمای مالی والد (§18): بسته‌های هر معلمِ فرزندان، پرداخت‌ها/فاکتورها
    با تاریخچه کامل، درخواست‌های بازپرداخت — فقط فرزندان متصل‌شده."""
    child_ids = await _child_ids(db, parent_id)

    packs: list[SessionPack] = []
    payments: list[PaymentTransaction] = []
    refunds: list[RefundRequest] = []
    if child_ids:
        packs = list(
            (
                await db.execute(
                    select(SessionPack)
                    .where(SessionPack.student_user_id.in_(child_ids))
                    .order_by(SessionPack.id.desc())
                )
            ).scalars()
        )
        payments = list(
            (
                await db.execute(
                    select(PaymentTransaction)
                    .where(
                        or_(
                            PaymentTransaction.student_user_id.in_(child_ids),
                            PaymentTransaction.payer_user_id == parent_id,
                        )
                    )
                    .order_by(PaymentTransaction.id.desc())
                )
            ).scalars()
        )
    pay_ids = [p.id for p in payments]
    if pay_ids:
        refunds = list(
            (
                await db.execute(
                    select(RefundRequest)
                    .where(RefundRequest.payment_id.in_(pay_ids))
                    .order_by(RefundRequest.id.desc())
                )
            ).scalars()
        )

    names = await _user_names(
        db,
        {
            *child_ids,
            parent_id,
            *[p.student_user_id for p in payments],
            *[p.tutor_user_id for p in payments],
            *[p.payer_user_id for p in payments],
            *[p.tutor_user_id for p in packs],
        },
    )
    children: list[User] = []
    if child_ids:
        children = list((await db.execute(select(User).where(User.id.in_(child_ids)))).scalars())

    by_status = _totals_by_status(payments)
    return {
        "children": [{"id": u.id, "full_name": u.full_name} for u in children],
        "packs": [_pack_row(p, names) for p in packs],
        "payments": [_payment_row(p, names) for p in payments],
        "refunds": [_refund_row(r, {p.id: p for p in payments}) for r in refunds],
        "stats": {
            "packs_total": len(packs),
            "sessions_purchased": sum(p.total_sessions for p in packs),
            "sessions_used": sum(p.used_sessions for p in packs),
            "sessions_remaining": sum(p.remaining for p in packs),
            "paid_total": by_status.get("paid", 0),
            "pending_total": by_status.get("pending", 0),
            "failed_total": by_status.get("failed", 0),
            "refunded_total": by_status.get("refunded", 0),
            "refunds_open": sum(1 for r in refunds if r.status == "requested"),
        },
        "payment_mode": "external",
        "mode_note_fa": MODE_NOTE_FA,
        "note_fa": (
            "مدل پرداخت (داخل یا خارج از سیستم) همان تصمیم باز بخش ۱۰.۲ سند دانش‌آموز است؛ "
            "این بخش صرفا واسط نمایش آن به والد است و پول بین خانواده و معلم جا به جا می‌شود."
        ),
    }


def _totals_by_status(payments: list[PaymentTransaction]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for p in payments:
        totals[p.status] = totals.get(p.status, 0) + p.amount
    return totals


async def list_packs(
    db: AsyncSession, *, parent_id: int | None = None, tutor_id: int | None = None
) -> dict:
    """فهرست بسته‌های جلسات: والد ⇒ فرزندان متصلش؛ معلم ⇒ بسته‌های خودش."""
    stmt = select(SessionPack)
    if parent_id is not None:
        child_ids = await _child_ids(db, parent_id)
        stmt = stmt.where(false()) if not child_ids else stmt.where(
            SessionPack.student_user_id.in_(child_ids)
        )
    elif tutor_id is not None:
        stmt = stmt.where(SessionPack.tutor_user_id == tutor_id)
    else:
        stmt = stmt.where(false())

    rows = list((await db.execute(stmt.order_by(SessionPack.id.desc()))).scalars())
    names = await _user_names(
        db, {r.student_user_id for r in rows} | {r.tutor_user_id for r in rows}
    )
    return {
        "packs": [_pack_row(r, names) for r in rows],
        "payment_mode": "external",
        "mode_note_fa": MODE_NOTE_FA,
    }


async def record_external_payment(
    db: AsyncSession,
    *,
    payer_user_id: int,
    student_user_id: int,
    tutor_user_id: int,
    amount: int,
    session_pack_id: int | None = None,
    session_count: int | None = None,
    subject: str | None = None,
    description: str | None = None,
) -> dict:
    """ثبت پرداخت انجام‌شده «خارج از سیستم» (گزینه الف §10.۲): وضعیت paid،
    فاکتور صادر می‌شود و در صورت اعلام تعداد جلسه، بسته جلسات فعال ساخته
    (یا بسته‌ی انتخاب‌شده پیوند/فعال) می‌شود. اعتبارسنجی دامنه در API است."""
    if amount <= 0:
        return {"ok": False, "reason": "مبلغ باید بزرگ‌تر از صفر باشد"}
    if session_count is not None and session_count < 1:
        return {"ok": False, "reason": "تعداد جلسات باید حداقل ۱ باشد"}

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    pack: SessionPack | None = None
    if session_pack_id is not None:
        pack = await db.get(SessionPack, session_pack_id)
        # دامنه در API (والد/معلم/دانش‌آموز) سنجیده شده؛ اینجا فقط پیوند/فعال‌سازی
        if pack is not None and pack.status == "cancelled":
            pack.status = "active"  # پرداخت، بسته لغوشده را دوباره فعال می‌کند
    elif session_count is not None:
        pack = SessionPack(
            student_user_id=student_user_id,
            tutor_user_id=tutor_user_id,
            subject=subject or "عمومی",
            total_sessions=session_count,
            used_sessions=0,
            price_per_session=amount // session_count,
            status="active",
        )
        db.add(pack)
        await db.flush()

    pay = PaymentTransaction(
        payer_user_id=payer_user_id,
        student_user_id=student_user_id,
        tutor_user_id=tutor_user_id,
        session_pack_id=pack.id if pack is not None else None,
        amount=amount,
        method="external",  # §10.۲: گزینه الف — پرداخت بین خانواده و معلم
        status="paid",
        description=description,
        paid_at=now,
    )
    db.add(pay)
    await db.flush()
    pay.invoice_no = f"INV-{pay.id:06d}"  # شماره فاکتور پایدار برای هر ردیف
    await db.flush()

    return {
        "ok": True,
        "payment_id": pay.id,
        "invoice_no": pay.invoice_no,
        "status": pay.status,
        "status_fa": PAYMENT_STATUS_FA[pay.status],
        "method": pay.method,
        "session_pack_id": pack.id if pack is not None else None,
    }


async def use_pack_session(db: AsyncSession, *, pack_id: int, tutor_user_id: int) -> dict:
    """معلم یک جلسه از بسته را مصرف می‌کند (گارد مالکیت بسته در API است).
    used_sessions هرگز از total_sessions بیشتر نمی‌شود."""
    pack = await db.get(SessionPack, pack_id)
    if pack is None or pack.tutor_user_id != tutor_user_id:
        return {"ok": False, "reason": "به این بسته دسترسی ندارید", "code": 403}
    if pack.used_sessions >= pack.total_sessions:
        return {"ok": False, "reason": "همه جلسات این بسته مصرف شده است", "code": 400}
    if pack.status != "active":
        return {"ok": False, "reason": "این بسته فعال نیست", "code": 400}

    pack.used_sessions += 1
    if pack.used_sessions >= pack.total_sessions:
        pack.status = "exhausted"
    await db.flush()
    return {
        "ok": True,
        "pack_id": pack.id,
        "used": pack.used_sessions,
        "purchased": pack.total_sessions,
        "remaining": pack.remaining,
        "status": pack.status,
        "status_fa": PACK_STATUS_FA.get(pack.status, pack.status),
    }


async def request_refund(
    db: AsyncSession, *, payment_id: int, parent_user_id: int, reason: str
) -> dict:
    """درخواست بازپرداخت والد برای جلسات لغوشده/برگزارنشده (§18).
    گارد پیوند والد–فرزند در API (403) اجرا می‌شود؛ اینجا اعتبار داخلی."""
    payment = await db.get(PaymentTransaction, payment_id)
    if payment is None:
        return {"ok": False, "reason": "پرداخت یافت نشد", "code": 403}
    if payment.status != "paid":
        return {"ok": False, "reason": "فقط پرداخت‌های پرداخت‌شده قابل بازپرداخت هستند", "code": 400}
    if not reason or not reason.strip():
        return {"ok": False, "reason": "دلیل بازپرداخت الزامی است", "code": 400}

    existing = (
        await db.execute(
            select(RefundRequest).where(
                RefundRequest.payment_id == payment_id,
                RefundRequest.status == "requested",
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        # قرارداد مخزن: تکراری → 409 (همانند پذیرش ثبت‌نام/افزودن سؤال)
        return {"ok": False, "reason": "درخواست بازپرداخت تکراری است", "code": 409}

    rf = RefundRequest(
        payment_id=payment_id,
        requested_by=parent_user_id,
        reason=reason.strip(),
        status="requested",
    )
    db.add(rf)
    await db.flush()
    return {
        "ok": True,
        "refund_id": rf.id,
        "status": rf.status,
        "status_fa": REFUND_STATUS_FA[rf.status],
        "invoice_no": payment.invoice_no,
    }


async def tutor_earnings(db: AsyncSession, tutor_user_id: int) -> dict:
    """دریافتی‌های معلم خصوصی: تجمیع پرداخت‌ها بر اساس وضعیت + مبالغ."""
    payments = list(
        (
            await db.execute(
                select(PaymentTransaction)
                .where(PaymentTransaction.tutor_user_id == tutor_user_id)
                .order_by(PaymentTransaction.id.desc())
            )
        ).scalars()
    )
    names = await _user_names(
        db,
        {
            *[p.student_user_id for p in payments],
            *[p.payer_user_id for p in payments],
            tutor_user_id,
        },
    )

    counts: dict[str, int] = {}
    totals: dict[str, int] = {}
    for p in payments:
        counts[p.status] = counts.get(p.status, 0) + 1
        totals[p.status] = totals.get(p.status, 0) + p.amount

    by_status = [
        {
            "status": st,
            "status_fa": PAYMENT_STATUS_FA.get(st, st),
            "count": counts[st],
            "total": totals[st],
        }
        for st in ("paid", "pending", "failed", "refunded")
        if st in counts
    ]
    return {
        "by_status": by_status,
        "total_earned": totals.get("paid", 0),
        "pending_amount": totals.get("pending", 0),
        "refunded_amount": totals.get("refunded", 0),
        "payments_count": len(payments),
        "payments": [_payment_row(p, names) for p in payments],
        "note_fa": (
            "مبالغ پرداخت‌های ثبت‌شده (خارج از سیستم — گزینه الف بخش ۱۰.۲) است؛ "
            "تسویه نهایی بین معلم و خانواده خارج از پلتفرم انجام می‌شود."
        ),
    }
