"""مدل‌های دستیار هوشمند معلم (سند پنل معلم §15 و §16):

- گفت‌وگوی کوپایلت روی «برش داده تجمیعی همان کلاس» (نه SLM یک
  دانش‌آموز)؛ هر پاسخ دارای «منبع بازیابی‌شده» و یادداشت «copilot است،
  نه تصمیم‌گیرنده».
- پیشنهاد اقدام §16: سیستم پیشنهاد می‌سازد؛ هیچ پیشنهادی (ارسال
  تمرین، ساخت آزمون، گزارش والدین، پیام به دانش‌آموز) بدون تأیید،
  ویرایش یا رد معلم اجرا نمی‌شود.

رویدادهای ممیزی مرتبط (ضمیمه ب سند): teacher_copilot_query،
ai_suggestion_approved / ai_suggestion_edited / ai_suggestion_rejected."""
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class TeacherCopilotConversation(Base):
    """گفت‌وگوی معلم با کوپایلت — محدود به کلاسِ تخصیص‌یافته همان معلم."""

    __tablename__ = "teacher_copilot_conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))  # معلمی که پرسیده
    title: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    messages = relationship(
        "TeacherCopilotMessage", back_populates="conversation", order_by="TeacherCopilotMessage.id"
    )


class TeacherCopilotMessage(Base):
    """هر پیام: intent تشخیص‌داده‌شده + منابع بازیابی‌شده برای شفافیت."""

    __tablename__ = "teacher_copilot_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("teacher_copilot_conversations.id"))
    role: Mapped[str] = mapped_column(String(12))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    intent: Mapped[str | None] = mapped_column(String(40))  # فقط پیام دستیار
    sources: Mapped[list | None] = mapped_column(JSON)  # [{type, id, title}]
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    conversation = relationship("TeacherCopilotConversation", back_populates="messages")


class TeacherSuggestion(Base):
    """پیشنهاد اقدام §16: وضعیت proposed ← approved | edited | rejected.

    kind نوع اجرای تأییدشده را تعیین می‌کند:
    - draft_exam: ساخت پیش‌نویس آزمون (payload.goal/topic_id)
    - send_practice: ایجاد کار مرور/تمرین برای دانش‌آموزان (payload.user_ids)
    - advice: فقط ثبت تصمیم (بدن اجرایی سمت سرور)"""

    __tablename__ = "teacher_suggestions"

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"))
    kind: Mapped[str] = mapped_column(String(30))  # draft_exam | send_practice | advice
    title_fa: Mapped[str] = mapped_column(String(300))
    evidence_fa: Mapped[str] = mapped_column(Text)  # جمله مجهز به اعداد واقعی
    actions_fa: Mapped[list] = mapped_column(JSON, default=list)  # گزینه‌های پیشنهادی
    payload: Mapped[dict] = mapped_column(JSON, default=dict)  # داده اجرای پس از تأیید
    status: Mapped[str] = mapped_column(String(20), default="proposed")
    # proposed | approved | edited | rejected
    final_actions_fa: Mapped[list | None] = mapped_column(JSON)  # بعد از ویرایش معلم
    result: Mapped[dict | None] = mapped_column(JSON)  # خروجی اجرا (exam_id / task_ids)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    decision_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
