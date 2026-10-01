"""مدل‌های بخش مالی (سند پنل والدین §18 + تصمیم باز §10.۲ سند دانش‌آموز).

پرداخت پیش‌فرض «خارج از سیستم» (گزینه الف) است: پول بین خانواده و معلم
جا به جا می‌شود و سیستم فقط ثبت‌کننده است. ستون method='internal' و فیلدهای
مانده‌ی امانی برای گزینه ب (پرداخت داخلی با کارمزد و نگه‌داری امانی تا
پایان جلسه) از همین حالا در مدل هستند تا فعال‌سازی آن نیازمند تغییر اسکیما
نباشد — اما هیچ منطق درگاه جعلی‌ای در سیستم وجود ندارد.

یکای مبلغ‌ها تومان است (عدد صحیح)."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

# برچسب‌های فارسی وضعیت‌ها — همین‌جا نگه داشته می‌شوند تا نمای API و UI یکی باشند
PAYMENT_STATUS_FA = {
    "pending": "در انتظار",
    "paid": "پرداخت‌شده",
    "failed": "ناموفق",
    "refunded": "بازپرداخت‌شده",
}
PACK_STATUS_FA = {"active": "فعال", "exhausted": "تمام‌شده", "cancelled": "لغوشده"}
REFUND_STATUS_FA = {"requested": "درخواست‌شده", "approved": "تأییدشده", "rejected": "ردشده"}
METHOD_FA = {"external": "خارج از سیستم", "internal": "داخل سیستم"}


class SessionPack(Base):
    """بسته جلسات خریداری‌شده برای یک دانش‌آموز نزد یک معلم خصوصی (§18)."""

    __tablename__ = "session_packs"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    tutor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    subject: Mapped[str] = mapped_column(String(50))
    total_sessions: Mapped[int] = mapped_column(Integer)
    used_sessions: Mapped[int] = mapped_column(Integer, default=0)
    price_per_session: Mapped[int | None] = mapped_column(Integer)  # تومان (اختیاری)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active|exhausted|cancelled
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    @property
    def remaining(self) -> int:
        """باقی‌مانده محاسبه‌ای (ذخیره نمی‌شود تا همیشه با used هم‌راستا باشد)."""
        return max(self.total_sessions - self.used_sessions, 0)


class PaymentTransaction(Base):
    """ثبت پرداخت (خارج یا داخل سیستم) — تاریخچه کامل تراکنش + فاکتور (§18).

    invoice_no با الگوی INV-{id:06d} و پس از flush ردیف ساخته می‌شود؛ برای هر
    ردیف پایدار است و دوباره تولید نمی‌شود."""

    __tablename__ = "payment_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    payer_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))  # والد یا دانش‌آموز پرداخت‌کننده
    student_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))  # ذی‌نفع
    tutor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    session_pack_id: Mapped[int | None] = mapped_column(ForeignKey("session_packs.id"))
    amount: Mapped[int] = mapped_column(Integer)  # تومان
    method: Mapped[str] = mapped_column(String(20), default="external")  # external|internal (§10.2)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|paid|failed|refunded
    invoice_no: Mapped[str | None] = mapped_column(String(20), unique=True)  # INV-000001 (بلافاصله پس از flush)
    description: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    paid_at: Mapped[datetime | None] = mapped_column(DateTime)


class RefundRequest(Base):
    """درخواست بازپرداخت برای جلسات لغوشده/برگزارنشده (§18) — والد ثبت می‌کند."""

    __tablename__ = "refund_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payment_transactions.id"))
    requested_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="requested")  # requested|approved|rejected
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    decision_note: Mapped[str | None] = mapped_column(String(300))
