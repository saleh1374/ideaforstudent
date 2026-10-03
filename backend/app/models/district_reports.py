"""جدول‌های ویژه‌ی پنل مدیر ناحیه (district spec §19 انتقال دانش‌آموز +
§31 گزارش‌های مدیریتی + §32 ارسال گزارش به استان).

همه جدول‌های «تازه» هستند — هیچ ستونی به جدول موجود اضافه نمی‌شود، پس
نیازی به migration در db.py نیست و داده‌های قبلی دست‌نخورده می‌مانند."""
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class StudentTransfer(Base):
    """انتقال دانش‌آموز بین مدارس ناحیه (§19).

    در انتقال هیچ داده‌ای حذف نمی‌شود: مدرسه/کلاس قبلی در همین ردیف نگه
    داشته می‌شود (سابقه)، پروفایل دانش‌آموز فقط به مدرسه جدید می‌رود و
    تأییدکننده + دلیل + تاریخ اثر برای ممیزی ثبت می‌ماند."""

    __tablename__ = "student_transfers"

    id: Mapped[int] = mapped_column(primary_key=True)
    district_id: Mapped[int] = mapped_column(ForeignKey("districts.id"))
    student_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    from_school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"))
    to_school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"))
    from_class_id: Mapped[int | None] = mapped_column(ForeignKey("classes.id"))
    to_class_id: Mapped[int | None] = mapped_column(ForeignKey("classes.id"))
    reason_fa: Mapped[str] = mapped_column(Text)
    effective_date: Mapped[date] = mapped_column(Date, default=date.today)
    status: Mapped[str] = mapped_column(String(20), default="approved")  # approved | cancelled
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class DistrictReport(Base):
    """گزارش رسمی ناحیه برای استان (§31/§32).

    پیش‌نویس قابل ویرایش است؛ پس از ارسال قفل می‌شود و اگر استان برگرداند
    دوباره قابل اصلاح و ارسال مجدد می‌شود — گردش: draft → submitted →
    reviewed → (returned | approved)."""

    __tablename__ = "district_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    district_id: Mapped[int] = mapped_column(ForeignKey("districts.id"))
    title_fa: Mapped[str] = mapped_column(String(200))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    # draft | submitted | reviewed | returned | approved
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    review_note: Mapped[str | None] = mapped_column(Text)
