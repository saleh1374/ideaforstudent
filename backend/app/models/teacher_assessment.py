"""آزمون صلاحیت معلم (سند صلاحیت — خواسته صریح کارفرما): «هر سال که به
معلمی درسی ارائه می‌شه، باید یه آزمون سنجش دانش همون درس و یه آزمون سنجش
مهارت مدیریت کلاس بگذرونه؛ نتیجه برای ناحیه قابل دید باشه».

بانک سؤالِ اختصاصیِ معلم (بدون وابستگی به مبحث کاتالوگ)، آزمون‌های سالانه
با نمونه‌برداری لحظه تخصیص، تلاش/پاسخ معلم، رکورد صلاحیت سالانه و
اقدام اصلاحی ناحیه (دوره/سرپرستی/جایگزینی)."""
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class TeacherExam(Base):
    """آزمون سالانه صلاحیت یک معلم: دو نوع (سنجش دانش درس | سنجش مدیریت
    کلاس) برای هر (معلم، درس، سال تحصیلی) — یکتا و بدون تکرار."""

    __tablename__ = "teacher_exams"
    __table_args__ = (
        UniqueConstraint(
            "teacher_user_id", "kind", "subject_key", "school_year",
            name="uq_teacher_exam_year",
        ),
        Index("ix_teacher_exams_district", "district_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(30))  # subject | classroom_management
    title_fa: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str | None] = mapped_column(String(50))  # فقط برای آزمون subject
    subject_key: Mapped[str] = mapped_column(String(50), default="")
    # نسخه غیر-NULL از subject برای یکتایی: در SQLite/PostgreSQL NULL در UNIQUE
    # مقایسه نمی‌شود (NULL != NULL) — آزمون مدیریت کلاس subject_key="" می‌گیرد
    school_year: Mapped[str] = mapped_column(String(9))  # مثل 1405-1406
    school_id: Mapped[int | None] = mapped_column(ForeignKey("schools.id"))
    district_id: Mapped[int] = mapped_column(ForeignKey("districts.id"))
    teacher_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    assigned_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="assigned")
    # assigned | in_progress | completed | expired
    due_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    items = relationship("TeacherExamItem", order_by="TeacherExamItem.order")


class TeacherExamQuestion(Base):
    """بانک سؤال صلاحیت معلم — جدای از بانک دانش‌آموز: این سؤال‌ها مبحث
    کاتالوگ ندارند (نه سؤال ریاضی دانش‌آموز، نه شاهد SLM)."""

    __tablename__ = "teacher_exam_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(30))  # subject | classroom_management
    subject: Mapped[str | None] = mapped_column(String(50))  # برای kind=subject
    body: Mapped[str] = mapped_column(Text)
    options: Mapped[dict] = mapped_column(JSON)  # {"A": "...", ...}
    correct_option: Mapped[str] = mapped_column(String(1))
    difficulty: Mapped[str] = mapped_column(String(10), default="medium")
    is_active: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class TeacherExamItem(Base):
    """نمونه برداشته‌شده از بانک در لحظه تخصیص — snapshot؛ اگر بانک بعداً
    عوض شود، آزمون‌های قدیمی دست‌نخورده می‌مانند."""

    __tablename__ = "teacher_exam_items"
    __table_args__ = (UniqueConstraint("exam_id", "order", name="uq_teacher_exam_item_order"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("teacher_exams.id"))
    question_id: Mapped[int] = mapped_column(ForeignKey("teacher_exam_questions.id"))
    order: Mapped[int] = mapped_column(Integer)
    points: Mapped[float] = mapped_column(Float, default=1.0)

    question = relationship("TeacherExamQuestion")


class TeacherExamAttempt(Base):
    """تلاش یک معلم برای یک آزمون — یک تلاش برای هر (آزمون، معلم)."""

    __tablename__ = "teacher_exam_attempts"
    __table_args__ = (
        UniqueConstraint("exam_id", "teacher_user_id", name="uq_teacher_attempt"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("teacher_exams.id"))
    teacher_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    percent: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), default="in_progress")
    # in_progress | submitted | graded
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class TeacherAttemptAnswer(Base):
    """پاسخ هر گزینه‌ای از تلاش معلم — بدون پاسخ هم ردیف ثبت می‌شود
    (selected_option=null و is_correct=0)."""

    __tablename__ = "teacher_attempt_answers"

    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("teacher_exam_attempts.id"))
    exam_item_id: Mapped[int] = mapped_column(ForeignKey("teacher_exam_items.id"))
    selected_option: Mapped[str | None] = mapped_column(String(1))
    is_correct: Mapped[int] = mapped_column(Integer, default=0)


class TeacherQualification(Base):
    """وضعیت صلاحیت معلم برای یک (درس، سال): نتیجه هر دو آزمون وقتی هر دو
    تصحیح شد ارزیابی می‌شود و برای ناحیه قابل مشاهده است."""

    __tablename__ = "teacher_qualifications"
    __table_args__ = (
        UniqueConstraint("teacher_user_id", "subject", "school_year", name="uq_teacher_qualification"),
        Index("ix_teacher_qualifications_district", "district_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    subject: Mapped[str] = mapped_column(String(50))
    school_year: Mapped[str] = mapped_column(String(9))
    school_id: Mapped[int | None] = mapped_column(ForeignKey("schools.id"))
    district_id: Mapped[int] = mapped_column(ForeignKey("districts.id"))
    subject_exam_id: Mapped[int | None] = mapped_column(ForeignKey("teacher_exams.id"))
    management_exam_id: Mapped[int | None] = mapped_column(ForeignKey("teacher_exams.id"))
    subject_percent: Mapped[float | None] = mapped_column(Float)
    management_percent: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # pending | qualified | probation | critical
    status_note: Mapped[str | None] = mapped_column(Text)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class TeacherIntervention(Base):
    """اقدام اصلاحی ناحیه روی صلاحیت بحرانی/آزمایشی: دوره ضمن خدمت،
    سرپرستی یا جایگزینی (خواسته کارفرفا: «ناحیه دوره ترتیب بده یا معلم رو
    عوض کنه»)."""

    __tablename__ = "teacher_interventions"

    id: Mapped[int] = mapped_column(primary_key=True)
    qualification_id: Mapped[int] = mapped_column(ForeignKey("teacher_qualifications.id"))
    type: Mapped[str] = mapped_column(String(20))  # training | mentoring | replacement
    status: Mapped[str] = mapped_column(String(20), default="proposed")
    # proposed | scheduled | done | cancelled
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
