"""مدل‌های دستیار هوشمند مدیر مدرسه (سند مدیر مدرسه §16 و §18):

- گفت‌وگوی کوپایلت با داده تجمیعی کل مدرسه (نه SLM یک دانش‌آموز)؛
  پاسخ‌ها همیشه دارای «منبع بازیابی‌شده» و یادداشت «تصمیم نهایی با مدیر».
- پیشنهاد اقدام §18: سیستم پیشنهاد می‌سازد؛ فقط با تأیید، ویرایش یا رد
  مدیر اجرا می‌شود (هوش مصنوعی copilot است، نه تصمیم‌گیرنده).

رویدادهای ممیزی مرتبط (ضمیمه ب سند): school_copilot_query،
school_suggestion_approved / school_suggestion_edited / school_suggestion_rejected."""
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class SchoolCopilotConversation(Base):
    """گفت‌وگوی مدیر با کوپایلت مدرسه — محدود به همان مدرسه."""

    __tablename__ = "school_copilot_conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))  # مدیری که پرسیده
    title: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    messages = relationship(
        "SchoolCopilotMessage", back_populates="conversation", order_by="SchoolCopilotMessage.id"
    )


class SchoolCopilotMessage(Base):
    """هر پیام: intent تشخیص‌داده‌شده + منابع بازیابی‌شده برای شفافیت."""

    __tablename__ = "school_copilot_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("school_copilot_conversations.id")
    )
    role: Mapped[str] = mapped_column(String(12))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    intent: Mapped[str | None] = mapped_column(String(40))  # فقط پیام دستیار
    sources: Mapped[list | None] = mapped_column(JSON)  # [{type, id, title}]
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    conversation = relationship("SchoolCopilotConversation", back_populates="messages")


class SchoolSuggestion(Base):
    """پیشنهاد اقدام §18: وضعیت proposed ← approved | edited | rejected.

    تصمیم با مدیر است؛ ردیفِ ردشده برای بهبود پیشنهادهای بعدی می‌ماند."""

    __tablename__ = "school_suggestions"

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"))
    class_id: Mapped[int | None] = mapped_column(ForeignKey("classes.id"))
    subject: Mapped[str | None] = mapped_column(String(50))
    title_fa: Mapped[str] = mapped_column(String(300))
    evidence_fa: Mapped[str] = mapped_column(Text)  # جمله مجهز به اعداد واقعی
    actions_fa: Mapped[list] = mapped_column(JSON, default=list)  # اقدام‌های پیشنهادی
    status: Mapped[str] = mapped_column(String(20), default="proposed")
    # proposed | approved | edited | rejected
    final_actions_fa: Mapped[list | None] = mapped_column(JSON)  # بعد از ویرایش مدیر
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    decision_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
