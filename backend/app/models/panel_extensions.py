"""جدول‌های تازهٔ پنل معلم و پنل مدیر مدرسه.

سند معلم: §5 «چرا؟»/خط زمان (از همان دادهٔ موجود ساخته می‌شود — جدول ندارد)،
§9 مأموریت کلاسی، §8.3 شخصی‌سازی آزمون برای هر دانش‌آموز، §14 گزارش والدین
توسط معلم؛ سند مدیر مدرسه: §9 دعوت معلم، §17 مداخلهٔ سطح مدرسه.

فقط جدول‌های «جدید» اینجا ساخته می‌شوند — هیچ ستونی به جدول‌های موجود اضافه
نمی‌شود و app/core/db.py دست‌نخورده می‌ماند. ثبت جدول‌ها در Base.metadata با
ایمپورت همین ماژول از app/api/teacher.py و app/api/admin.py انجام می‌شود.
"""
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ClassMission(Base):
    """§9 مأموریت کالسی — الگوی «هدف معلم ← اجرای سیستم ← سنجش»."""

    __tablename__ = "class_missions"

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), index=True)
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id"))  # مبحث هدف (اختیاری)
    title_fa: Mapped[str] = mapped_column(String(200))
    target_mastery: Mapped[float] = mapped_column(Float)  # حداقل تسط هدف (٪)
    deadline: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | completed | archived
    baseline_mastery: Mapped[float | None] = mapped_column(Float)  # تسط کلاس در لحظهٔ تعریف
    target_students: Mapped[list] = mapped_column(JSON, default=list)  # دانش‌آموزان زیر آستانه
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    result_note_fa: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class TeacherParentReport(Base):
    """§14 گزارش والدین توسط معلم — پیش‌نویس تولیدشده از دادهٔ موجود، قابل
    ویرایش توسط معلم پیش از ارسال (بدون اطلاعات سایر دانش‌آموزان)."""

    __tablename__ = "teacher_parent_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int | None] = mapped_column(ForeignKey("classes.id"))
    student_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    teacher_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title_fa: Mapped[str] = mapped_column(String(200))
    body_fa: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | edited | sent
    generated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    edited_at: Mapped[datetime | None] = mapped_column(DateTime)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)


class ExamStudentPersonalization(Base):
    """§8.3 شخصی‌سازی آزمون: تمرکز هر دانش‌آموز (A مفهوم / B محاسبات / C زمان)
    در حالت «تشخیصی شخصی» — انتخاب دستی معلم روی پیشنهاد خودکار."""

    __tablename__ = "exam_student_personalization"
    __table_args__ = (UniqueConstraint("exam_id", "student_user_id", name="uq_exam_student_focus"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"))
    student_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    focus: Mapped[str] = mapped_column(String(1))  # A | B | C
    note_fa: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=datetime.utcnow)


class TeacherInvitation(Base):
    """§9 سند مدیر مدرسه — گام سوم افزودن معلم: «ارسال دعوت ← فعال‌شدن حساب»."""

    __tablename__ = "teacher_invitations"

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), index=True)
    full_name: Mapped[str] = mapped_column(String(150))
    phone: Mapped[str | None] = mapped_column(String(15))
    subject: Mapped[str | None] = mapped_column(String(50))
    note: Mapped[str | None] = mapped_column(Text)
    invite_code: Mapped[str] = mapped_column(String(12), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | accepted | cancelled
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)


class SchoolIntervention(Base):
    """§17 سند مدیر مدرسه + §25/§26 سند ناحیه — مداخلهٔ سطح مدرسه با مالک،
    وضعیت و اثر قابل اندازه‌گیری: Before → Intervention → Retest → After →
    Retention check."""

    __tablename__ = "school_interventions"

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), index=True)
    class_id: Mapped[int | None] = mapped_column(ForeignKey("classes.id"))  # هدف: کلاس
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id"))  # هدف: مبحث
    title_fa: Mapped[str] = mapped_column(String(200))
    description_fa: Mapped[str | None] = mapped_column(Text)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))  # مسئول اجرا
    status: Mapped[str] = mapped_column(String(20), default="planned")  # planned | in_progress | done | evaluated
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    due_at: Mapped[date | None] = mapped_column(Date)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    mastery_before: Mapped[float | None] = mapped_column(Float)  # سنجش پیش از مداخله
    mastery_after: Mapped[float | None] = mapped_column(Float)  # سنجش پس از مداخله
    retention_check: Mapped[float | None] = mapped_column(Float)  # سنجش ماندگاری
    outcome_fa: Mapped[str | None] = mapped_column(Text)
