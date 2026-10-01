"""SLM + Planner models (student spec §2.2, §2.4, §4.3, §5.6, §6):
per-student topic state with history, soft evidence, error book, and the
daily plan of remedial/spaced-review tasks."""
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class StudentTopicState(Base):
    """One row per student × topic; history list keeps every update so the
    «ضعیف → بهبود → افت» pattern stays detectable forever (spec §2.2)."""

    __tablename__ = "student_topic_states"
    __table_args__ = (UniqueConstraint("student_user_id", "topic_id", name="uq_state_student_topic"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    student_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"))

    mastery: Mapped[float] = mapped_column(Float, default=0.0)          # M
    retention: Mapped[float] = mapped_column(Float, default=0.0)        # R at last computation
    stability: Mapped[float] = mapped_column(Float, default=4.0)        # S (days)
    effective_mastery: Mapped[float] = mapped_column(Float, default=0.0)  # E shown in dashboards
    evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    last_evidence_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_state_change: Mapped[datetime | None] = mapped_column(DateTime)
    errors_by_cause: Mapped[dict] = mapped_column(JSON, default=dict)   # {cause: {"total":n,"unresolved":n}}
    history: Mapped[list] = mapped_column(JSON, default=list)           # [{at, source, M, E, ...}]

    topic = relationship("Topic")


class Evidence(Base):
    """Soft evidence feed into SLM. Official exams weight 1.0, AI chat 0.15…"""

    __tablename__ = "evidences"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"))
    skill_id: Mapped[int | None] = mapped_column(ForeignKey("skills.id"))
    source: Mapped[str] = mapped_column(String(30))
    # period_exam | cumulative | quiz | retest | practice | ai_chat | self_report | tutoring
    weight: Mapped[float] = mapped_column(Float)
    correct: Mapped[int] = mapped_column(Integer, default=1)
    partial_credit: Mapped[float] = mapped_column(Float, default=0.0)   # c_i in 0..1
    flagged_guess: Mapped[int] = mapped_column(Integer, default=0)      # c_i = 0.5 if guessed
    difficulty_weight: Mapped[float] = mapped_column(Float, default=1.0)  # d_i
    occurred_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    attempt_answer_id: Mapped[int | None] = mapped_column(ForeignKey("attempt_answers.id"))

    topic = relationship("Topic")


class ErrorRecord(Base):
    """دفترچه خطا — one row per error with its lifecycle (created → resolved
    → possible relapse). Also feeds class/school/district error analytics."""

    __tablename__ = "error_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    attempt_answer_id: Mapped[int] = mapped_column(ForeignKey("attempt_answers.id"))
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"))
    skill_id: Mapped[int | None] = mapped_column(ForeignKey("skills.id"))
    cause: Mapped[str] = mapped_column(String(20))
    item_snapshot: Mapped[dict] = mapped_column(JSON)  # متن سؤال/گزینه‌ها در لحظه خطا
    status: Mapped[str] = mapped_column(String(20), default="open")
    # open | in_remediation | resolved | relapsed
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    relapsed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PlanTask(Base):
    """Daily plan task (student spec §4.3): lesson, practice, remedial pack,
    spaced review, retest… priority = severity×repeat×exam_proximity×weight."""

    __tablename__ = "plan_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id"))
    task_type: Mapped[str] = mapped_column(String(30))
    # lesson | practice | remedial_pack | spaced_review | retest | quiz | cumulative_prep
    payload: Mapped[dict] = mapped_column(JSON, default=dict)  # مثلا بسته ترمیمی یا کارت مرور
    for_date: Mapped[Date] = mapped_column(Date)
    priority: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|done|missed|moved
    minicheck_passed: Mapped[int] = mapped_column(Integer, default=0)  # «مطالعه شد» فقط با گذراندن آزمونک
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    topic = relationship("Topic")
