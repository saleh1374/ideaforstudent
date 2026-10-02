"""مدل‌های عملیات روزانه مدرسه (سند مدیر مدرسه — پنل کامل مدیر):

- SchoolShift: شیفت‌های متغیر هر مدرسه (تک‌شیفت مثلاً ۰۸:۰۰–۱۵:۰۰ یا دو شیفت
  ۰۸:۰۰–۱۲:۰۰ و ۱۲:۰۰–۱۸:۰۰) — ساعت‌ها را خود مدیر مدرسه تعریف می‌کند.
- ClassScheduleEntry: برنامه هفتگی هر کلاس (روز هفته × بازه ساعتی × درس ×
  معلم). داده واحدی که پنل دانش‌آموز و پنل معلم هم از همان می‌خوانند تا
  «هر تغییری همه‌جا هماهنگ بماند».

شیفتِ یک معلم از روی همین برنامه استخراج می‌شود (بازه‌های درسی‌اش در کدام
شیفت می‌افتد) — یک منبع حقیقت، بدون جدول موازی."""
from datetime import datetime

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class SchoolShift(Base):
    """شیفت کاری مدرسه — ساعت‌ها متغیر و با تأیید مدیر مدرسه."""

    __tablename__ = "school_shifts"
    __table_args__ = (UniqueConstraint("school_id", "name", name="uq_school_shift_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"))
    name: Mapped[str] = mapped_column(String(60))  # «شیفت صبح» / «شیفت اول»
    start_time: Mapped[str] = mapped_column(String(5))  # HH:MM — مثلاً 08:00
    end_time: Mapped[str] = mapped_column(String(5))  # HH:MM — مثلاً 15:00
    order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ClassScheduleEntry(Base):
    """یک جلسه در برنامه هفتگی یک کلاس؛ day: 0=شنبه ... 6=جمعه."""

    __tablename__ = "class_schedule"
    __table_args__ = (UniqueConstraint("class_id", "day", "start_time", name="uq_class_day_start"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"))
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"))  # برای پرسش‌های سطح مدرسه
    day: Mapped[int] = mapped_column(Integer)  # 0=شنبه ... 6=جمعه
    start_time: Mapped[str] = mapped_column(String(5))  # HH:MM
    end_time: Mapped[str] = mapped_column(String(5))  # HH:MM
    subject: Mapped[str] = mapped_column(String(50))
    teacher_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))  # ممکن است خالی باشد
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
