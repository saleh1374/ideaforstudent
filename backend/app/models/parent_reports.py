"""کش گزارش هفتگی پنل والدین (سند پنل والدین §14).

جدولِ مخصوصِ همین بخش است: ستونی به جدول‌های موجود اضافه نمی‌شود و فقط وقتی
والد گزارش هفته‌ی جاری را می‌خواهد (یا صراحتاً تازه می‌کند) نوشته می‌شود —
ساخت گزارش را idempotent و ارزان نگه می‌دارد."""
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ParentWeeklyReport(Base):
    """یک ردیف برای هر (والد × فرزند × هفته)؛ payload کامل گزارش در JSON."""

    __tablename__ = "parent_weekly_reports"
    __table_args__ = (
        UniqueConstraint("parent_user_id", "student_user_id", "week_start", name="uq_parent_week_student"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    student_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    week_start: Mapped[date] = mapped_column(Date)
    generated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
