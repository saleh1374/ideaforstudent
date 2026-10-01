"""Materialized topic statistics (roadmap phase 7 «مدیر استان/وزارت»):
tجمیع ذخیره‌شده topic-level برای استان و کشور؛ با قاعده حریم خصوصی
حداقل جمعیت ۱۰ نفر هنگام محاسبه اعمال می‌شود."""
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    Float,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class NationalTopicStat(Base):
    """یک ردیف = یک مبحث در یک دامنه (کل کشور یا یک استان)."""

    __tablename__ = "national_topic_stats"
    __table_args__ = (
        UniqueConstraint("scope", "province_id", "topic_id", name="uq_topic_stat_scope"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    scope: Mapped[str] = mapped_column(String(12))  # national | province
    province_id: Mapped[int] = mapped_column(Integer, default=0)  # 0 برای national
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"))
    subject: Mapped[str | None] = mapped_column(String(50))
    students_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_mastery: Mapped[float | None] = mapped_column(Float)     # None وقتی جمعیت < حد نصاب
    avg_retention: Mapped[float | None] = mapped_column(Float)
    weak_ratio: Mapped[float | None] = mapped_column(Float)      # سهم زیر آستانه تثبیت
    is_suppressed: Mapped[int] = mapped_column(Integer, default=0)  # 1 = زیر حداقل جمعیت
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
