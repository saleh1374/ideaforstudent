"""Phase 0 — Organizational core: Province → District → School → Class, and
User → Employee → Employment → SchoolAssignment (RBAC spec §2, §4, §5)."""
from datetime import date

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class Province(Base):
    __tablename__ = "provinces"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    code: Mapped[str] = mapped_column(String(10), unique=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())


class District(Base):
    __tablename__ = "districts"

    id: Mapped[int] = mapped_column(primary_key=True)
    province_id: Mapped[int] = mapped_column(ForeignKey("provinces.id"))
    name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())


class School(Base):
    """School is a first-class entity (RBAC spec §2) — not a text field."""

    __tablename__ = "schools"

    id: Mapped[int] = mapped_column(primary_key=True)
    district_id: Mapped[int] = mapped_column(ForeignKey("districts.id"))
    province_id: Mapped[int] = mapped_column(ForeignKey("provinces.id"))
    name: Mapped[str] = mapped_column(String(150))
    school_code: Mapped[str] = mapped_column(String(20), unique=True)
    school_type: Mapped[str] = mapped_column(String(20))  # primary | middle | high_school | combined
    ownership_type: Mapped[str] = mapped_column(String(20))  # public | non_profit | private
    address: Mapped[str | None] = mapped_column(String(300))
    academic_year: Mapped[str] = mapped_column(String(9), default="1405-1406")
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())

    district = relationship("District")


class ClassRoom(Base):
    __tablename__ = "classes"
    __table_args__ = (UniqueConstraint("school_id", "grade", "name", name="uq_class_school_grade_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"))
    grade: Mapped[str] = mapped_column(String(20))  # grade_10 | grade_11 | grade_12
    track: Mapped[str | None] = mapped_column(String(30))  # math | experimental | ... (رشته)
    name: Mapped[str] = mapped_column(String(50))
    capacity: Mapped[int | None] = mapped_column(Integer)
    academic_year: Mapped[str] = mapped_column(String(9), default="1405-1406")
    status: Mapped[str] = mapped_column(String(20), default="active")


class User(Base):
    """Base identity: login + system role hint. Staff identity is separate
    (Employee); students/parents also live here."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    full_name: Mapped[str] = mapped_column(String(150))
    national_id: Mapped[str | None] = mapped_column(String(10), unique=True)
    phone: Mapped[str | None] = mapped_column(String(15))
    system_role: Mapped[str] = mapped_column(String(30), default="student")
    # student | parent | teacher | school_admin | district_admin | province_admin | ministry | platform_admin
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())

    employee = relationship("Employee", back_populates="user", uselist=False)


class Employee(Base):
    """Staff identity layer, independent from any school (RBAC spec §4)."""

    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    personnel_code: Mapped[str | None] = mapped_column(String(20), unique=True)
    education_degree: Mapped[str | None] = mapped_column(String(50))
    major: Mapped[str | None] = mapped_column(String(100))
    years_of_experience: Mapped[int | None] = mapped_column(Integer)

    user = relationship("User", back_populates="employee")
    employments = relationship("Employment", back_populates="employee")


class Employment(Base):
    """Employment type is an entity with history, not an enum (RBAC spec §5)."""

    __tablename__ = "employments"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    employment_type: Mapped[str] = mapped_column(String(20))
    # official | contractual | part_time | temporary | other
    organization: Mapped[str] = mapped_column(String(20))
    # government | school | private | district (کارکنان اداری ناحیه)
    district_id: Mapped[int | None] = mapped_column(ForeignKey("districts.id"))
    # ناحیه برای کارکنان اداری ناحیه (پنل مدیر ناحیه §12 — Employment organization="district")
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="active")

    employee = relationship("Employee", back_populates="employments")


class SchoolAssignment(Base):
    """Assignment of a staff member to a school with role and dates.
    Old assignment closes with end_date; identity never changes (RBAC spec §4)."""

    __tablename__ = "school_assignments"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"))
    role: Mapped[str] = mapped_column(String(30))
    # principal | deputy | teacher | district_staff | ...
    subject: Mapped[str | None] = mapped_column(String(50))  # برای معلم
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="active")

    employee = relationship("Employee")
    school = relationship("School")


class ClassTeacherAssignment(Base):
    """تخصیص دبیر به کلاس (سند دانش‌آموز §2.3) — معلم فقط به کلاس‌هایی که
    به او تخصیص یافته دسترسی دارد (سند معلم §18)."""

    __tablename__ = "class_teacher_assignments"
    __table_args__ = (UniqueConstraint("class_id", "teacher_user_id", "subject", name="uq_class_teacher_subject"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"))
    teacher_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    subject: Mapped[str] = mapped_column(String(50))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="active")

    class_room = relationship("ClassRoom")


class StudentProfile(Base):
    """Student-specific data hanging off User."""

    __tablename__ = "student_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    grade: Mapped[str] = mapped_column(String(20))
    track: Mapped[str | None] = mapped_column(String(30))
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"))
    class_id: Mapped[int | None] = mapped_column(ForeignKey("classes.id"))
    entry_year: Mapped[str | None] = mapped_column(String(9))
    status: Mapped[str] = mapped_column(String(20), default="active")

    user = relationship("User")
    school = relationship("School")
    class_room = relationship("ClassRoom")


class ParentLink(Base):
    """Parent ↔ student link (parent panel spec §17)."""

    __tablename__ = "parent_links"
    __table_args__ = (UniqueConstraint("parent_user_id", "student_user_id", name="uq_parent_student"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    student_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    relation: Mapped[str | None] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="active")
