"""AI assistant models (roadmap phase 6 «دستیار هوشمند»): conversation log,
per-message model tier (small/large) + retrieved sources, and the semantic
cache that short-circuits repeat questions. Chat-derived learning signals go
into the existing Evidence table with source='ai_chat' (weight 0.15)."""
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


class AiConversation(Base):
    __tablename__ = "ai_conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    messages = relationship("AiMessage", back_populates="conversation", order_by="AiMessage.id")


class AiMessage(Base):
    """model_tier: small (پاسخ کوتاه/کش‌شده) | large (استدلال بلند) —
    مسیریابی بر اساس پیچیدگی پرسش؛ sources رگای را برای شفافیت نگه می‌دارد."""

    __tablename__ = "ai_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("ai_conversations.id"))
    role: Mapped[str] = mapped_column(String(12))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    model_tier: Mapped[str | None] = mapped_column(String(10))  # small | large
    sources: Mapped[list | None] = mapped_column(JSON)  # [{type, id, title}]
    cached: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    conversation = relationship("AiConversation", back_populates="messages")


class SemanticCache(Base):
    """کش معنایی: پرسش نرمال‌شده → پاسخ. تکرار پرسش بدون فراخوانی مدل."""

    __tablename__ = "semantic_cache"

    id: Mapped[int] = mapped_column(primary_key=True)
    query_norm: Mapped[str] = mapped_column(Text, unique=True)
    query_original: Mapped[str] = mapped_column(Text)
    response: Mapped[str] = mapped_column(Text)
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_hit_at: Mapped[datetime | None] = mapped_column(DateTime)
