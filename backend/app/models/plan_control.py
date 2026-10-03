"""کنترل بار برنامه (student spec §4.3 «سقف بار روزانه» + «توقف موقت»).

جدول‌های جدید به‌جای افزودن ستون به جدول‌های موجود؛ وضعیت توقف برای هر
دانش‌آموز فقط یک بازهٔ فعال دارد و زنجیرهٔ فعالیت (streak §8.7) با توقف
موقت نمی‌شکند."""
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class PlanPause(Base):
    """توقف موقت برنامه (§4.3): حداکثر ۱۴ روز؛ در بازگشت، سیستم برنامهٔ
    جبرانی فشرده می‌سازد و زنجیرهٔ فعالیت پابرجا می‌ماند."""

    __tablename__ = "plan_pauses"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)  # تا این تاریخ برنامه متوقف است
    reason_fa: Mapped[str | None] = mapped_column(String(200))  # بیماری، سفر، ...
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | finished
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class DailyLoadLog(Base):
    """ثبت تصمیم‌های سقف بار روزانه: کارهایی که به روز آزاد بعدی منتقل شدند
    و پیام فارسی توضیح (§4.3 «بقیه به روز آزاد بعدی منتقل می‌شوند»)."""

    __tablename__ = "daily_load_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    day: Mapped[date] = mapped_column(Date)
    cap_minutes: Mapped[int] = mapped_column(Integer, default=0)
    used_minutes: Mapped[int] = mapped_column(Integer, default=0)
    moved_task_ids: Mapped[list] = mapped_column(JSON, default=list)
    message_fa: Mapped[str | None] = mapped_column(String(400))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
