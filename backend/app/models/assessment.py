"""Assessment core (student spec §5, §2.3): question bank with rich metadata,
official exams with blueprint, per-item org snapshot, and grading.
Snapshot fields on each attempt answer: «در زمان آن آزمون، این دانش‌آموز
در کدام کلاس و با کدام دبیر/مدرسه/ناحیه/استان بود؟» — بدون این، هیچ تحلیل
تاریخی قابل بازتولید نیست."""
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    JSON,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class QuestionItem(Base):
    __tablename__ = "question_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"))
    skill_id: Mapped[int | None] = mapped_column(ForeignKey("skills.id"))
    body: Mapped[str] = mapped_column(Text)
    options: Mapped[dict] = mapped_column(JSON)  # {"A": "...", "B": "...", "C": "...", "D": "..."}
    correct_option: Mapped[str] = mapped_column(String(1))
    difficulty: Mapped[str] = mapped_column(String(10), default="medium")  # easy|medium|hard
    difficulty_weight: Mapped[float] = mapped_column(Float, default=1.2)  # d_i: 1.0/1.2/1.5
    misconception: Mapped[str | None] = mapped_column(String(200))  # کج‌فهمی مرتبط
    distractor_causes: Mapped[dict | None] = mapped_column(JSON)
    # {"B": "conceptual", "C": "calculation"} — هر گزینه غلط می‌تواند علت خطا برانگیزد
    is_active: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    topic = relationship("Topic")


class Exam(Base):
    """period_exam | cumulative | quiz | diagnostic | remedial_retest | practice"""

    __tablename__ = "exams"

    id: Mapped[int] = mapped_column(primary_key=True)
    title_fa: Mapped[str] = mapped_column(String(200))
    exam_type: Mapped[str] = mapped_column(String(30))
    grade: Mapped[str] = mapped_column(String(20))
    subject: Mapped[str] = mapped_column(String(50))
    # scope: exam can be national/district/school/class; official exams feed boards
    scope: Mapped[str] = mapped_column(String(20), default="class")
    school_id: Mapped[int | None] = mapped_column(ForeignKey("schools.id"))
    class_id: Mapped[int | None] = mapped_column(ForeignKey("classes.id"))
    period_id: Mapped[int | None] = mapped_column(ForeignKey("periods.id"))
    blueprint: Mapped[dict | None] = mapped_column(JSON)  # [{"topic_id":1,"count":3,"difficulty_mix":{...}}]
    negative_marking_k: Mapped[float] = mapped_column(Float, default=0.0)  # §5.4 اصلاحیه: per-grade tunable
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|published|closed|graded
    opens_at: Mapped[datetime | None] = mapped_column(DateTime)
    closes_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    exam_items = relationship("ExamItem", back_populates="exam", order_by="ExamItem.order")


class ExamItem(Base):
    __tablename__ = "exam_items"
    __table_args__ = (UniqueConstraint("exam_id", "order", name="uq_exam_item_order"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("question_items.id"))
    order: Mapped[int] = mapped_column(Integer)
    points: Mapped[float] = mapped_column(Float, default=1.0)

    exam = relationship("Exam", back_populates="exam_items")
    item = relationship("QuestionItem")


class ExamAttempt(Base):
    __tablename__ = "exam_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"))
    student_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    raw_score: Mapped[float | None] = mapped_column(Float)
    percent: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), default="in_progress")
    # in_progress | submitted | graded

    exam = relationship("Exam")
    answers = relationship("AttemptAnswer", back_populates="attempt")


class AttemptAnswer(Base):
    """One row per answered item, with the organizational snapshot frozen at
    submit time + error cause classification."""

    __tablename__ = "attempt_answers"

    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("exam_attempts.id"))
    exam_item_id: Mapped[int] = mapped_column(ForeignKey("exam_items.id"))
    student_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    selected_option: Mapped[str | None] = mapped_column(String(1))
    is_correct: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[int | None] = mapped_column(Integer)          # 1..5
    answer_changes: Mapped[int] = mapped_column(Integer, default=0)   # تعداد تغییر پاسخ
    time_spent_ms: Mapped[int] = mapped_column(Integer, default=0)
    question_position: Mapped[int] = mapped_column(Integer, default=0)

    # ---- org snapshot (spec §2.11) ----
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"))
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"))
    teacher_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    district_id: Mapped[int] = mapped_column(ForeignKey("districts.id"))
    province_id: Mapped[int] = mapped_column(ForeignKey("provinces.id"))

    # ---- error classification (student spec §6) ----
    error_cause: Mapped[str | None] = mapped_column(String(20))
    # conceptual | prerequisite | calculation | careless | time_management | guess
    error_resolved: Mapped[int] = mapped_column(Integer, default=0)
    error_relapsed: Mapped[int] = mapped_column(Integer, default=0)

    attempt = relationship("ExamAttempt", back_populates="answers")
    exam_item = relationship("ExamItem")
