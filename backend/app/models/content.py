"""محتوای مبحث (student spec §3.4 «بستهٔ محتوایی مبحث» + §10.1 نردبان کمک:
پرسش نوشتاری دانش‌آموز از دبیر کالس که وارد کارتابل دبیر می‌شود."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class TopicQuestion(Base):
    """پرسش دانش‌آموز دربارهٔ یک مبحث — بخش ۷ بستهٔ محتوایی «پرسش از دبیر»."""

    __tablename__ = "topic_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"))
    class_id: Mapped[int | None] = mapped_column(ForeignKey("classes.id"))  # کالس دبیرِ مقصد
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="sent")  # sent | answered
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    answered_at: Mapped[datetime | None] = mapped_column(DateTime)

    topic = relationship("Topic")
