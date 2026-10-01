"""Private-tutor marketplace models (roadmap phase 8 «معلم خصوصی»):
بازار معلم‌ها + درخواست جلسه + گفت‌وگوی گروهی با قواعد ایمنی زیر ۱۸
(بدون افشای شماره تماس/نشانی در چت + دکمه گزارش + ثبت ممیزی)."""
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class TutorProfile(Base):
    """نمایه معلم خصوصی — فقط معلمان فعال می‌توانند بسازند."""

    __tablename__ = "tutor_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    headline: Mapped[str | None] = mapped_column(String(200))
    subjects: Mapped[list] = mapped_column(JSON, default=list)  # ["math", "physics"]
    bio: Mapped[str | None] = mapped_column(Text)
    session_price: Mapped[int | None] = mapped_column(Integer)  # تومان (اختیاری)
    availability: Mapped[str | None] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user = relationship("User")


class TutorRequest(Base):
    """درخواست جلسه دانش‌آموز/والد از معلم."""

    __tablename__ = "tutor_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    tutor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    subject: Mapped[str] = mapped_column(String(50))
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|accepted|rejected
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class TutorGroup(Base):
    """گروه گفت‌وگوی معلم با دانش‌آموزانش (چت گروهی فاز ۸)."""

    __tablename__ = "tutor_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    tutor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(150))
    subject: Mapped[str] = mapped_column(String(50))
    is_open: Mapped[bool] = mapped_column(Boolean, default=True)  # امکان پیوستن
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    members = relationship("TutorGroupMember", back_populates="group")


class TutorGroupMember(Base):
    __tablename__ = "tutor_group_members"
    __table_args__ = (UniqueConstraint("group_id", "student_user_id", name="uq_tutor_group_member"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("tutor_groups.id"))
    student_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    joined_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    group = relationship("TutorGroup", back_populates="members")


class TutorMessage(Base):
    """پیام گروه/درخواست. flagged وقتی فیلتر ایمنی شماره تماس/پیوند را زد."""

    __tablename__ = "tutor_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("tutor_groups.id"))
    request_id: Mapped[int | None] = mapped_column(ForeignKey("tutor_requests.id"))
    sender_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    content: Mapped[str] = mapped_column(Text)
    flagged: Mapped[int] = mapped_column(Integer, default=0)
    report_reason: Mapped[str | None] = mapped_column(String(300))  # گزارش کاربر
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
