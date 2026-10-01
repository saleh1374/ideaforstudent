"""سرویس ثبت‌نام دانش‌آموز (Feature B): اعتبارسنجی نام کاربری/پایه تحصیلی،
کنترل یکتایی نام کاربری در کاربران و درخواست‌های در انتظار، و انتخاب
کلاس پیش‌فرض هنگام تأیید — منطق مشترک بین /auth/register و /admin/students."""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.org import AdmissionRequest, ClassRoom, User

# نام کاربری: حروف/عدد/نقطه/تیره/زیرخط (ادبیات فارسی هم مجاز) — بدون فاصله
USERNAME_RE = re.compile(r"^[\w.\-]{1,64}$", re.UNICODE)

# پایه‌های تحصیلی مجاز (همان قرارداد StudentProfile.grade)
ALLOWED_GRADES = {f"grade_{n}" for n in range(7, 13)}

DUP_USERNAME = "نام کاربری قبلاً استفاده شده"


def username_format_ok(username: str) -> bool:
    """قالب نام کاربری معتبر است؟ (خالی/فاصله/نمادهای غیرمجوز رد می‌شوند)"""
    return bool(USERNAME_RE.match(username))


def grade_ok(grade: str) -> bool:
    """پایه تحصیلی در محدوده مجاز (grade_7 تا grade_12) است؟"""
    return grade in ALLOWED_GRADES


async def username_taken(db: AsyncSession, username: str) -> bool:
    """یکتایی نام کاربری: هم بین کاربران موجود، هم بین درخواست‌های در انتظار —
    تا تأییدِ بعدی هرگز با کاربر دیگری تداخل نکند."""
    if (await db.execute(select(User.id).where(User.username == username))).first() is not None:
        return True
    pending = (
        await db.execute(
            select(AdmissionRequest.id).where(
                AdmissionRequest.username == username,
                AdmissionRequest.status == "pending",
            )
        )
    ).first()
    return pending is not None


async def first_class_of_school(db: AsyncSession, school_id: int) -> int | None:
    """نخستین کلاس (قدیمی‌ترین) مدرسه برای تخصیص پیش‌فرض هنگام تأیید —
    اگر مدرسه کلاسی نداشته باشد None برمی‌گردد (کلاس در پروفایل اختیاری است)."""
    row = (
        await db.execute(
            select(ClassRoom.id).where(ClassRoom.school_id == school_id).order_by(ClassRoom.id)
        )
    ).first()
    return row[0] if row is not None else None
