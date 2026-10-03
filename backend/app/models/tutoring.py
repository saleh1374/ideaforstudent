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


class TutorVerification(Base):
    """تأیید صالحیت معلم خصوصی (سند دانش‌آموز §10.2-۲):
    پیش‌نویس ← ارسال‌شده ← در بررسی ← تأییدشده/ردشده/نیازمند تکمیل ← تعلیق‌شده.
    کد ملی به‌صورت هش‌شده با کلید سراسری ذخیره می‌شود، نه متن ساده (§18)."""

    __tablename__ = "tutor_verifications"
    __table_args__ = (UniqueConstraint("profile_id", name="uq_tutor_verification_profile"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("tutor_profiles.id"))
    status: Mapped[str] = mapped_column(String(24), default="draft")
    full_name: Mapped[str | None] = mapped_column(String(150))
    national_id_hash: Mapped[str | None] = mapped_column(String(80))
    national_id_masked: Mapped[str | None] = mapped_column(String(12))
    degree: Mapped[str | None] = mapped_column(String(120))
    university: Mapped[str | None] = mapped_column(String(150))
    teaching_certificate: Mapped[str | None] = mapped_column(String(150))
    experience_years: Mapped[int | None] = mapped_column(Integer)
    intro: Mapped[str | None] = mapped_column(Text)
    expertise_topics: Mapped[list] = mapped_column(JSON, default=list)  # [topic_id, ...] برای پیشنهاد هوشمند
    accepts_under18: Mapped[bool] = mapped_column(Boolean, default=False)
    police_clearance: Mapped[int] = mapped_column(Integer, default=0)  # گواهی عدم سوءپیشینه
    review_note: Mapped[str | None] = mapped_column(String(300))
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ParentConsent(Base):
    """رضایت والد برای دانش‌آموز زیر ۱۸ سال (§10.2-۵): بدون تأیید والد، درخواست به معلم نمی‌رسد."""

    __tablename__ = "parent_consents"
    __table_args__ = (UniqueConstraint("request_id", name="uq_parent_consent_request"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("tutor_requests.id"))
    parent_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|approved|rejected
    note: Mapped[str | None] = mapped_column(String(300))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class TutorSession(Base):
    """کارت جلسه (§10.2-۸): معلم لینک، تاریخ و موضوع را ثبت می‌کند؛ دانش‌آموز با
    «ورود به کلاس» حضورش ثبت می‌شود و معلم در پایان تأیید می‌کند."""

    __tablename__ = "tutor_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    tutor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    student_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    group_id: Mapped[int | None] = mapped_column(ForeignKey("tutor_groups.id"))
    request_id: Mapped[int | None] = mapped_column(ForeignKey("tutor_requests.id"))
    starts_at: Mapped[datetime] = mapped_column(DateTime)
    duration_min: Mapped[int] = mapped_column(Integer, default=60)
    topic: Mapped[str] = mapped_column(String(200))
    join_link: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(16), default="scheduled")  # scheduled|completed|cancelled
    attended_at: Mapped[datetime | None] = mapped_column(DateTime)
    tutor_confirmed: Mapped[int] = mapped_column(Integer, default=0)
    lesson_note: Mapped[str | None] = mapped_column(Text)  # یادداشت جلسه
    homework: Mapped[str | None] = mapped_column(Text)  # تکلیف → وارد برنامهٔ دانش‌آموز
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class TutorFeedback(Base):
    """امتیاز و بازخورد دانش‌آموز و والد (§10.2-۹) — تجمیعی به معلم نمایش داده می‌شود."""

    __tablename__ = "tutor_feedbacks"
    __table_args__ = (UniqueConstraint("session_id", "from_user_id", name="uq_tutor_feedback_session_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("tutor_sessions.id"))
    from_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    from_role: Mapped[str] = mapped_column(String(16))  # student|parent
    rating: Mapped[int] = mapped_column(Integer)  # 1..5
    comment: Mapped[str | None] = mapped_column(String(400))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class TutorInvite(Base):
    """کد دعوت امن به گروه (§10.2-۵ پیشنهاد اصلاحی): بدون جست‌وجوی کد ملی."""

    __tablename__ = "tutor_invites"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("tutor_groups.id"))
    code: Mapped[str] = mapped_column(String(12), unique=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
