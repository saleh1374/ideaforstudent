"""جدول‌های تکمیلی پنل والدین (سند پنل والدین §9 حضور و جلسات، §11/§12
معلم خصوصی از دید والد، §17 مجوزهای هر پیوند والد–فرزند).

همه جدول‌های نو هستند — ستونی به جدول‌های موجود (از جمله parent_links)
اضافه نمی‌شود؛ مجوز هر پیوند در ردیف جداگانه ثبت می‌شود تا پیوندهای
موجودِ بدون مجوز، «دسترسی کامل» بمانند (سازگاری عقب‌رو)."""
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ParentLinkPermission(Base):
    """مجوزِ مستقلِ هر پیوند والد–فرزند (§17: «هر رابطه والد–فرزند مجوز
    مستقل دارد»).

    نبودِ ردیف برای یک کلید یعنی مجاز (پیش‌ردیف = دسترسی کامل)، پس
    پیوندهای ساخته‌شده در seed بدون تغییر رفتار می‌کنند."""

    __tablename__ = "parent_link_permissions"
    __table_args__ = (UniqueConstraint("link_id", "key", name="uq_parent_link_perm"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    link_id: Mapped[int] = mapped_column(ForeignKey("parent_links.id"))
    key: Mapped[str] = mapped_column(String(40))
    allowed: Mapped[int] = mapped_column(Integer, default=1)  # 1 = مجاز، 0 = غیرمجاز
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SchoolAttendance(Base):
    """حضور روزانه‌ی دانش‌آموز در مدرسه (§9: حضور مدرسه)."""

    __tablename__ = "school_attendance"
    __table_args__ = (UniqueConstraint("student_user_id", "on_date", name="uq_attendance_day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    student_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    school_id: Mapped[int | None] = mapped_column(ForeignKey("schools.id"))
    on_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="present")  # present|absent|late|excused
    note: Mapped[str | None] = mapped_column(String(300))
    recorded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ParentMeeting(Base):
    """جلسه‌ی دانش‌آموز از دید والد (§9: جلسات خصوصی گذشته/آینده، جلسات
    ازدست‌رفته، موضوع هر جلسه، تکلیف جلسه و وضعیت انجام آن)."""

    __tablename__ = "parent_meetings"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    tutor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(30), default="private_session")
    # private_session | school_session | parent_meeting
    subject: Mapped[str | None] = mapped_column(String(50))
    topic_fa: Mapped[str | None] = mapped_column(String(300))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime)
    duration_min: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="scheduled")  # scheduled|held|missed|cancelled
    report_fa: Mapped[str | None] = mapped_column(Text)   # گزارش معلم
    task_fa: Mapped[str | None] = mapped_column(String(300))  # تکلیف جلسه
    task_status: Mapped[str | None] = mapped_column(String(20))  # pending|done|skipped
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class TutorSatisfaction(Base):
    """سیگنال رضایت والد از معلم خصوصی (§11/§12: «امتیاز و بازخورد») —
    جدا از داده‌ی آموزشی و فقط از دید همان والد."""

    __tablename__ = "tutor_satisfaction"
    __table_args__ = (
        UniqueConstraint(
            "parent_user_id", "student_user_id", "tutor_user_id", name="uq_parent_tutor_rating"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    student_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    tutor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    rating: Mapped[int] = mapped_column(Integer, default=5)  # ۱ تا ۵
    comment: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
