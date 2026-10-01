"""مدل‌های ویژه پنل ناحیه (district spec §20–§21, §25–§27): آزمون رسمی
ناحیه، مداخله آموزشی با سنجش اثر و مأموریت آموزشی مدارس.

همه جدول‌های این ماژول «جدید» هستند — هیچ ستونی به جدول‌های مشترک
(assessment/org/…) اضافه نمی‌شود و فقط با import این ماژول در
`app/api/district.py` روی Base ثبت می‌شوند (parallel-safe).

آزمون رسمی ناحیه عمداً یک ردیف «پیوندی» به جدول موجود `exams` دارد تا
جریان موجود دانش‌آموز (start/submit)، تصحیح، شواهد SLM و دفترچه خطا بدون
تکرارپذیری کار کند — فقط scope آن district است."""
from datetime import date, datetime

from sqlalchemy import (
    Date,
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


class DistrictExam(Base):
    """آزمون رسمی ناحیه (§20): پایه + درس + جدول مشخصات + زمان‌بندی +
    مدارس انتخابی. چرخه وضعیت: draft → published → graded → closed.

    exam_id: ردیف همان `Exam` موجود (scope='district') که دانش‌آموزان
    از طریق جریان موجود پاسخ می‌دهند؛ نتایج/تحلیل سؤال از همان‌جا خوانده
    می‌شود."""

    __tablename__ = "district_exams"
    __table_args__ = (Index("ix_district_exams_district", "district_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    district_id: Mapped[int] = mapped_column(ForeignKey("districts.id"))
    exam_id: Mapped[int | None] = mapped_column(ForeignKey("exams.id"))  # آزمون پیوندی (backing)
    title_fa: Mapped[str] = mapped_column(String(200))
    grade: Mapped[str] = mapped_column(String(20))
    subject: Mapped[str] = mapped_column(String(50))
    blueprint: Mapped[str | None] = mapped_column(Text)  # جدول مشخصات/سرفصل آزمون
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|published|graded|closed
    opens_at: Mapped[datetime | None] = mapped_column(DateTime)
    closes_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    schools = relationship("DistrictExamSchool", back_populates="exam")


class DistrictExamSchool(Base):
    """مدرسه‌های انتخاب‌شده برای یک آزمون رسمی ناحیه."""

    __tablename__ = "district_exam_schools"
    __table_args__ = (UniqueConstraint("exam_id", "school_id", name="uq_district_exam_school"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("district_exams.id"))
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"))

    exam = relationship("DistrictExam", back_populates="schools")


class DistrictIntervention(Base):
    """مداخله آموزشی ناحیه (§25–§26): هدف مشخص + مدارس هدف + چرخه کامل
    اندازه‌گیری Before → After → Retest/Retention با «سنجش اثر مداخله».

    مقادیر تسلط (درصد ۰..۱۰۰) به‌صورت صریح توسط ناحیه ثبت می‌شوند؛ اگر
    before داده نشود و مبحث مشخص باشد، سرویس خودش از تجمیع SLM می‌خواند."""

    __tablename__ = "district_interventions"
    __table_args__ = (Index("ix_district_interventions_district", "district_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    district_id: Mapped[int] = mapped_column(ForeignKey("districts.id"))
    title_fa: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(30))  # course|supervision|replacement|program
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id"))
    grade: Mapped[str | None] = mapped_column(String(20))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    before_mastery: Mapped[float | None] = mapped_column(Float)  # پیش از مداخله (٪)
    after_mastery: Mapped[float | None] = mapped_column(Float)  # پس از بازآزمون (٪)
    retention_mastery: Mapped[float | None] = mapped_column(Float)  # ماندگاری ~۳ هفته بعد (٪)
    after_measured_at: Mapped[datetime | None] = mapped_column(DateTime)
    retention_measured_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active|closed|cancelled
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)

    schools = relationship("DistrictInterventionSchool", back_populates="intervention")


class DistrictInterventionSchool(Base):
    __tablename__ = "district_intervention_schools"
    __table_args__ = (
        UniqueConstraint("intervention_id", "school_id", name="uq_district_intervention_school"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    intervention_id: Mapped[int] = mapped_column(ForeignKey("district_interventions.id"))
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"))

    intervention = relationship("DistrictIntervention", back_populates="schools")


class DistrictMission(Base):
    """مأموریت آموزشی برای مدارس (§27): «طی دو هفته، تسلط مبحث X به حداقل
    ٪Y برسد.» وضعیت هر مدرسه و کل مأموریت از روی تجمیع تسط همان مبحث
    (با قاعده حداقل جمعیت) به‌صورت خودکار استخراج می‌شود."""

    __tablename__ = "district_missions"
    __table_args__ = (Index("ix_district_missions_district", "district_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    district_id: Mapped[int] = mapped_column(ForeignKey("districts.id"))
    title_fa: Mapped[str] = mapped_column(String(200))
    goal: Mapped[str] = mapped_column(Text)  # بیانیه هدف (مثلاً «تسلط بر مشتق تا حداقل ٪۷۰»)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"))
    target_mastery: Mapped[float] = mapped_column(Float)  # آستانه هدف (٪)
    deadline: Mapped[date] = mapped_column(Date)  # پیش‌فرض ~۲ هفته
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    schools = relationship("DistrictMissionSchool", back_populates="mission")


class DistrictMissionSchool(Base):
    __tablename__ = "district_mission_schools"
    __table_args__ = (UniqueConstraint("mission_id", "school_id", name="uq_district_mission_school"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    mission_id: Mapped[int] = mapped_column(ForeignKey("district_missions.id"))
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"))

    mission = relationship("DistrictMission", back_populates="schools")
