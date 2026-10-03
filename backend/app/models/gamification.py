"""نظام امتیاز و پاداش سبک (student spec §8.4 نشان‌ها، §8.6 امتیاز XP،
§8.7 ثبات مطالعه) — فقط برای کار یادگیری واقعی؛ جایگزین شاخص‌های تسلط نمی‌شود.

XP در جدول رویداد (به‌جای یک ستون جمع‌شونده) ثبت می‌شود تا:
  • سقف‌های روزانه (مثلاً ۳۰ XP تمرین در هر مبحث در روز) قابل‌محاسبه باشند،
  • زنجیرهٔ روزهای فعال از روی روزهای متمایز رویداد ساخته شود،
  • تاریخچهٔ پاداش‌ها برای دانش‌آموز قابل‌مشاهده بماند."""
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class XpEvent(Base):
    """یک ردیف = یک امتیاز کسب‌شده (§8.6 جدول «XP per action»)."""

    __tablename__ = "xp_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    day: Mapped[date] = mapped_column(Date)          # روز برای سقف روزانه/زنجیره
    action: Mapped[str] = mapped_column(String(30))  # lesson_completed | practice_correct | ...
    xp: Mapped[int] = mapped_column(Integer, default=0)
    ref_type: Mapped[str | None] = mapped_column(String(20))  # task | exam | topic | attempt
    ref_id: Mapped[int | None] = mapped_column(Integer)
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id"))
    detail_fa: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
