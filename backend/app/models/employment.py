"""Employment workflow models (RBAC spec §5): request + configurable policy
table. Policy is data, not hard-coded logic («جدول سیاست، نه منطق سخت‌کدشده»)."""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    JSON,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class EmploymentRequest(Base):
    __tablename__ = "employment_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"))
    requested_by: Mapped[int] = mapped_column(ForeignKey("users.id"))  # مدیر مدرسه
    employee_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    full_name: Mapped[str] = mapped_column(String(150))
    employment_type: Mapped[str] = mapped_column(String(20))
    organization: Mapped[str] = mapped_column(String(20))
    subject: Mapped[str | None] = mapped_column(String(50))
    role: Mapped[str] = mapped_column(String(30), default="teacher")

    status: Mapped[str] = mapped_column(String(20), default="pending")
    # pending | approved | rejected | auto_approved
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    decision_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class EmploymentPolicyRule(Base):
    """One row per (school_ownership × employment_type) combination.
    requires_district_approval is configurable at runtime."""

    __tablename__ = "employment_policy_rules"
    __table_args__ = (
        UniqueConstraint("school_ownership", "employment_type", name="uq_employment_policy"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    school_ownership: Mapped[str] = mapped_column(String(20))  # public | non_profit | private
    employment_type: Mapped[str] = mapped_column(String(20))   # official | contractual | part_time | temporary
    requires_district_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str | None] = mapped_column(String(200))
