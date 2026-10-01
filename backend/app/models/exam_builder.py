"""سازنده آزمون هوشمند معلم و تحلیل پس از آزمون (سند پنل معلم §8 و §10).

فقط جدول‌های «جدید» در این ماژول ساخته می‌شوند — هیچ ستونی به جدول‌های
 موجود اضافه نمی‌شود و app/core/db.py دست‌نخورده می‌ماند. ثبت جدول‌ها در
 Base.metadata با ایمپورت همین ماژول از app/api/teacher.py انجام می‌شود.
"""
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ExamBuilderProfile(Base):
    """وضعیت سازندهٔ هر آزمون: حالت برگزاری (§8.3 — استاندارد/تشخیصی شخصی) و
    هدف آزادِ معلم (§8.2). ردیف‌های بلوپرینت پیشنهادی در ستون JSON خودِ
    exams.blueprint ذخیره می‌شوند (شکل سازگار با موجود: [{topic_id, count, …}])
    تا ستون از قبل‌بوده بی‌استفاده نماند."""

    __tablename__ = "exam_builder_profiles"
    __table_args__ = (UniqueConstraint("exam_id", name="uq_exam_builder_profile"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"))
    mode: Mapped[str] = mapped_column(String(30), default="standard")  # standard | personal_diagnostic
    goal: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ItemAnalysis(Base):
    """تحلیل آیتم هر سؤالِ آزمون پس از برگزاری (§10.1) + پرچم خودکار
    «نیازمند بازبینی» (§10.2). پرچم و معیارها در همین جدول اختصاصی نگهداری
    می‌شوند، نه روی بانک سؤالِ موجود question_items."""

    __tablename__ = "item_analyses"
    __table_args__ = (UniqueConstraint("exam_id", "exam_item_id", name="uq_item_analysis"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"))
    exam_item_id: Mapped[int] = mapped_column(ForeignKey("exam_items.id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("question_items.id"))

    responses_count: Mapped[int] = mapped_column(Integer, default=0)   # تعداد پاسخ ثبت‌شده
    correct_pct: Mapped[float] = mapped_column(Float, default=0.0)     # درصد پاسخ صحیح
    empirical_difficulty: Mapped[float] = mapped_column(Float, default=0.0)  # d تجربی (p-value)
    prior_difficulty: Mapped[float | None] = mapped_column(Float)      # d پیش‌فرض از difficulty سؤال
    discrimination: Mapped[float | None] = mapped_column(Float)        # قدرت تفکیک ۲۷٪ بالا/پایین
    avg_time_ms: Mapped[int | None] = mapped_column(Integer)           # میانگین زمان پاسخ (در صورت داده)
    top_wrong_option: Mapped[str | None] = mapped_column(String(1))    # پرتکرارترین گزینه غلط
    top_wrong_pct: Mapped[float | None] = mapped_column(Float)         # سهم آن گزینه از کل خطاها
    misconception: Mapped[str | None] = mapped_column(String(300))     # کج‌همی/علت مرتبط (فارسی)
    comment_fa: Mapped[str | None] = mapped_column(Text)               # نظر خودکار فارسی
    needs_review: Mapped[int] = mapped_column(Integer, default=0)      # §10.2 پرچم «نیازمند بازبینی»
    review_reasons: Mapped[list | None] = mapped_column(JSON)          # دلایل فارسی پرچم
    computed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
