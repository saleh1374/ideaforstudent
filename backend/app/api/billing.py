"""بخش مالی API (سند پنل والدین §18 + تصمیم باز §10.۲ سند دانش‌آموز).

پرداخت پیش‌فرض «خارج از سیستم» (گزینه الف) است: سیستم فقط ثبت و فاکتور
صادر می‌کند؛ پول بین خانواده و معلم جا به جا می‌شود. گارد دامنه همیشه پیش
از چک وجود اجرا می‌شود ⇒ شناسه ناشناس/خارج از حوزه 403 می‌دهد (قرارداد
پلتفرم). تکراری بودن درخواست بازپرداخت: 409 (همانند سایر مخازن)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthUser, get_current_user
from app.core.db import get_db
from app.models import billing as billing_models  # noqa: F401  (ثبت جدول‌های بخش مالی)
from app.models.billing import PaymentTransaction, RefundRequest, SessionPack
from app.models.org import ParentLink, User
from app.services import billing as billing_svc
from app.services.rbac_service import log_action

router = APIRouter(prefix="/billing", tags=["billing"])


async def _require_linked_child(db: AsyncSession, parent_id: int, student_id: int) -> None:
    """پیوند فعال والد–فرزند برای همه‌ی endpointهای مالی فرزند؛ بدون پیوند ⇒ 403."""
    link = (
        await db.execute(
            select(ParentLink).where(
                ParentLink.parent_user_id == parent_id,
                ParentLink.student_user_id == student_id,
                ParentLink.status == "active",
            )
        )
    ).scalar_one_or_none()
    if link is None:
        raise HTTPException(403, "این دانش‌آموز به شما متصل نیست")


async def _names(db: AsyncSession, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    rows = (await db.execute(select(User.id, User.full_name).where(User.id.in_(ids)))).all()
    return {r[0]: r[1] for r in rows}


# --------------------------------------------------- نمای مالی والد (§18)


@router.get("/parent/overview")
async def parent_overview(current: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """بسته‌های جلسات + پرداخت‌ها/فاکتورها + بازپرداختها فقط برای فرزندان متصل."""
    if current.system_role != "parent":
        raise HTTPException(403, "فقط والد می‌تواند بخش مالی را ببیند")
    return await billing_svc.parent_overview(db, current.id)


# -------------------------------------------- ثبت پرداخت خارج از سیستم


class PaymentIn(BaseModel):
    student_user_id: int
    tutor_user_id: int
    amount: int  # تومان
    session_pack_id: int | None = None
    session_count: int | None = None  # ساخت بسته جلسات هنگام ثبت پرداخت
    subject: str | None = None
    description: str | None = None


@router.post("/payments")
async def record_payment(
    body: PaymentIn,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """والد پرداخت انجام‌شده خارج از سیستم را ثبت می‌کند (گزینه الف §10.۲)."""
    if current.system_role != "parent":
        raise HTTPException(403, "فقط والد می‌تواند پرداخت ثبت کند")
    # گارد دامنه پیش از هر چک وجود
    await _require_linked_child(db, current.id, body.student_user_id)

    tutor = await db.get(User, body.tutor_user_id)
    if tutor is None or tutor.system_role != "teacher":
        raise HTTPException(404, "معلم یافت نشد")

    if body.session_pack_id is not None:
        pack = await db.get(SessionPack, body.session_pack_id)
        if (
            pack is None
            or pack.student_user_id != body.student_user_id
            or pack.tutor_user_id != body.tutor_user_id
        ):
            raise HTTPException(403, "این بسته به این دانش‌آموز/معلم تعلق ندارد")

    result = await billing_svc.record_external_payment(
        db,
        payer_user_id=current.id,
        student_user_id=body.student_user_id,
        tutor_user_id=body.tutor_user_id,
        amount=body.amount,
        session_pack_id=body.session_pack_id,
        session_count=body.session_count,
        subject=body.subject,
        description=body.description,
    )
    if not result.get("ok"):
        raise HTTPException(400, result.get("reason"))
    await log_action(
        db,
        actor_user_id=current.id,
        action="payment_recorded",
        entity_type="payment",
        entity_id=result["payment_id"],
        detail=f"invoice={result['invoice_no']} amount={body.amount} method=external",
    )
    await db.commit()
    return result


# ------------------------------------------------- فاکتور یک پرداخت


@router.get("/payments/{payment_id}")
async def payment_detail(
    payment_id: int,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """نمای فاکتور: پرداخت‌کننده، معلمِ طرف تراکنش یا والدِ متصل به دانش‌آموز."""
    pay = await db.get(PaymentTransaction, payment_id)
    allowed = False
    if pay is not None:
        if pay.payer_user_id == current.id or pay.tutor_user_id == current.id:
            allowed = True
        else:
            link = (
                await db.execute(
                    select(ParentLink).where(
                        ParentLink.parent_user_id == current.id,
                        ParentLink.student_user_id == pay.student_user_id,
                        ParentLink.status == "active",
                    )
                )
            ).scalar_one_or_none()
            allowed = link is not None
    if not allowed:
        raise HTTPException(403, "به این فاکتور دسترسی ندارید")

    names = await _names(db, {pay.payer_user_id, pay.student_user_id, pay.tutor_user_id})
    refunds = list(
        (
            await db.execute(
                select(RefundRequest)
                .where(RefundRequest.payment_id == pay.id)
                .order_by(RefundRequest.id.desc())
            )
        ).scalars()
    )
    pack = await db.get(SessionPack, pay.session_pack_id) if pay.session_pack_id else None
    return {
        "payment": billing_svc._payment_row(pay, names),
        "refunds": [billing_svc._refund_row(r, {pay.id: pay}) for r in refunds],
        "pack": billing_svc._pack_row(pack, names) if pack is not None else None,
        "mode_note_fa": billing_svc.MODE_NOTE_FA,
    }


# ------------------------------------------------- درخواست بازپرداخت (§18)


class RefundIn(BaseModel):
    reason: str


@router.post("/payments/{payment_id}/refund")
async def request_refund(
    payment_id: int,
    body: RefundIn,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """والد برای جلسات لغوشده/برگزارنشده بازپرداخت درخواست می‌کند."""
    if current.system_role != "parent":
        raise HTTPException(403, "فقط والد می‌تواند بازپرداخت درخواست دهد")
    pay = await db.get(PaymentTransaction, payment_id)
    link = None
    if pay is not None:
        link = (
            await db.execute(
                select(ParentLink).where(
                    ParentLink.parent_user_id == current.id,
                    ParentLink.student_user_id == pay.student_user_id,
                    ParentLink.status == "active",
                )
            )
        ).scalar_one_or_none()
    if pay is None or link is None:
        raise HTTPException(403, "به این پرداخت دسترسی ندارید")

    result = await billing_svc.request_refund(
        db, payment_id=payment_id, parent_user_id=current.id, reason=body.reason
    )
    if not result.get("ok"):
        raise HTTPException(int(result.get("code", 400)), result.get("reason"))
    await log_action(
        db,
        actor_user_id=current.id,
        action="refund_requested",
        entity_type="payment",
        entity_id=payment_id,
        detail=f"refund={result['refund_id']} invoice={result.get('invoice_no')}",
    )
    await db.commit()
    return result


# ------------------------------------------- بسته‌های جلسات (والد / معلم)


@router.get("/packs")
async def list_packs(current: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """والد: بسته‌های فرزندان متصل. معلم: بسته‌های خودش. سایر نقش‌ها: 403."""
    if current.system_role == "parent":
        return await billing_svc.list_packs(db, parent_id=current.id)
    if current.system_role == "teacher":
        return await billing_svc.list_packs(db, tutor_id=current.id)
    raise HTTPException(403, "فقط والد یا معلم می‌تواند بسته‌های جلسات را ببیند")


@router.post("/packs/{pack_id}/use")
async def use_pack_session(
    pack_id: int,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """معلم یک جلسه از بسته‌اش را مصرف می‌کند؛ از سقف بسته نمی‌گذرد."""
    if current.system_role != "teacher":
        raise HTTPException(403, "فقط معلم می‌تواند مصرف جلسه را ثبت کند")
    # گارد مالکیت پیش از چک وجود (ناشناس/بسته‌ی دیگری ⇒ 403)
    pack = await db.get(SessionPack, pack_id)
    if pack is None or pack.tutor_user_id != current.id:
        raise HTTPException(403, "به این بسته دسترسی ندارید")

    result = await billing_svc.use_pack_session(db, pack_id=pack_id, tutor_user_id=current.id)
    if not result.get("ok"):
        raise HTTPException(int(result.get("code", 400)), result.get("reason"))
    await log_action(
        db,
        actor_user_id=current.id,
        action="pack_session_used",
        entity_type="session_pack",
        entity_id=pack_id,
        detail=f"used={result['used']}/{result['purchased']}",
    )
    await db.commit()
    return result


# --------------------------------------------- دریافتی‌های معلم خصوصی


@router.get("/tutor/earnings")
async def tutor_earnings(current: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """تجمیع پرداخت‌های دریافتی معلم بر اساس وضعیت (§18 — سمت معلم)."""
    if current.system_role != "teacher":
        raise HTTPException(403, "فقط معلم می‌تواند دریافتی‌ها را ببیند")
    return await billing_svc.tutor_earnings(db, current.id)
