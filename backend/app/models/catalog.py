"""Content catalog: Book → Chapter → Topic → Subtopic → Skill, with a
directed prerequisite graph across grades (student spec §2.1), and the
standard academic calendar with 14-day periods (student spec §4)."""
from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class Book(Base):
    __tablename__ = "books"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject: Mapped[str] = mapped_column(String(50))   # math | physics | chemistry | ...
    grade: Mapped[str] = mapped_column(String(20))
    title_fa: Mapped[str] = mapped_column(String(200))
    print_year: Mapped[str | None] = mapped_column(String(9))
    status: Mapped[str] = mapped_column(String(20), default="approved")  # کاتالوگ مرکزی، تأییدشده

    chapters = relationship("Chapter", back_populates="book", order_by="Chapter.order")


class Chapter(Base):
    __tablename__ = "chapters"

    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"))
    title_fa: Mapped[str] = mapped_column(String(200))
    order: Mapped[int] = mapped_column(Integer)
    exam_weight: Mapped[float] = mapped_column(default=1.0)  # وزن در آزمون

    book = relationship("Book", back_populates="chapters")
    topics = relationship("Topic", back_populates="chapter", order_by="Topic.order")


class Topic(Base):
    __tablename__ = "topics"

    id: Mapped[int] = mapped_column(primary_key=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id"))
    title_fa: Mapped[str] = mapped_column(String(200))
    order: Mapped[int] = mapped_column(Integer)
    period_id: Mapped[int | None] = mapped_column(ForeignKey("periods.id"))
    blueprint_weight: Mapped[float] = mapped_column(default=1.0)
    content_status: Mapped[str] = mapped_column(String(20), default="pending")
    # pending | generating | published (بسته محتوایی مبحث)

    chapter = relationship("Chapter", back_populates="topics")
    period = relationship("Period")
    skills = relationship("Skill", back_populates="topic")


class Skill(Base):
    """Smallest assessable unit; every item maps to at least one skill."""

    __tablename__ = "skills"

    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"))
    title_fa: Mapped[str] = mapped_column(String(200))

    topic = relationship("Topic", back_populates="skills")


class Prerequisite(Base):
    """Directed graph topic → prerequisite topic (spec: «پیش‌نیازها به صورت
    گراف جهت‌دار ذخیره می‌شوند... حتی از پایه‌های قبل»)."""

    __tablename__ = "prerequisites"
    __table_args__ = (UniqueConstraint("topic_id", "prereq_topic_id", name="uq_prerequisite"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"))
    prereq_topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"))


class Period(Base):
    """Standard 14-day learning period (spec §4.1)."""

    __tablename__ = "periods"

    id: Mapped[int] = mapped_column(primary_key=True)
    academic_year: Mapped[str] = mapped_column(String(9), default="1405-1406")
    number: Mapped[int] = mapped_column(Integer)
    start_date: Mapped[Date] = mapped_column(Date)
    end_date: Mapped[Date] = mapped_column(Date)
    has_cumulative_exam: Mapped[int] = mapped_column(Integer, default=0)  # پس از دوره‌های 4/8/12


class TopicPeriod(Base):
    """Maps topics to their teaching period per academic year (وسط default
    تقویم استاندارد؛ استان/مدرسه می‌توانند بعداً تنظیم کنند)."""

    __tablename__ = "topic_periods"
    __table_args__ = (UniqueConstraint("topic_id", "period_id", name="uq_topic_period"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"))
    period_id: Mapped[int] = mapped_column(ForeignKey("periods.id"))
