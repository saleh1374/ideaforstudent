"""Parent panel APIs (roadmap phase 5، سند پنل والدین §17).

والد فقط فرزندان متصل‌شده (ParentLink) را می‌بیند؛ داده تجمیعی و بدون
مقایسه با دانش‌آموزان دیگر — اصل حفظ حریم خصوصی کودک."""
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthUser, get_current_user
from app.core.db import get_db
from app.models import parent_reports  # noqa: F401  (ثبت جدول کش گزارش هفتگی)
from app.models.org import ParentLink, StudentProfile, User
from app.models.parent_reports import ParentWeeklyReport
from app.models.slm import ErrorRecord
from app.services import parent_reports as reports
from app.services.rbac_service import log_action
from app.services.slm import status_of

router = APIRouter(prefix="/parent", tags=["parent"])


async def _my_children(db: AsyncSession, parent_id: int) -> list[User]:
    links = (
        await db.execute(
            select(ParentLink).where(
                ParentLink.parent_user_id == parent_id, ParentLink.status == "active"
            )
        )
    ).scalars().all()
    if not links:
        return []
    ids = [l.student_user_id for l in links]
    return list((await db.execute(select(User).where(User.id.in_(ids)))).scalars())


async def _require_child(db: AsyncSession, parent_id: int, student_id: int) -> None:
    """همه‌ی endpointهای فرزند ابتدا پیوند فعال والد–فرزند را می‌سنجد؛
    بدون پیوند ⇒ 403 (سند §17، همان پیام و کد موجود برای overview)."""
    link = (
        await db.execute(
            select(ParentLink).where(
                ParentLink.parent_user_id == parent_id,
                ParentLink.student_user_id == student_id,
                ParentLink.status == "active",
            )
        )
    ).scalar_one_or_none()
    if link is None:
        raise HTTPException(403, "این دانش‌آموز به شما متصل نیست")


@router.get("/children")
async def children(current: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    users = await _my_children(db, current.id)
    out = []
    for u in users:
        profile = (
            await db.execute(select(StudentProfile).where(StudentProfile.user_id == u.id))
        ).scalar_one_or_none()
        out.append(
            {
                "id": u.id,
                "full_name": u.full_name,
                "grade": profile.grade if profile else None,
                "class_id": profile.class_id if profile else None,
            }
        )
    return {"children": out}


@router.get("/children/{student_id}/overview")
async def child_overview(
    student_id: int,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """نمای کلان فرزند: دو شاخص جدا (پیشرفت ≠ تسط) + وضعیت مباحث + خطاهای باز.
    بدون رتبه و بدون مقایسه با هم‌کلاسی‌ها (سند والدین)."""
    await _require_child(db, current.id, student_id)

    # دو شاخص و توزیع وضعیت مباحث از همان سرویس گزارش‌ها می‌آید تا عدد
    # overview، هشدارها و گزارش هفتگی همیشه با هم هم‌راستا باشند.
    pm = await reports.progress_mastery(db, student_id)
    topics = pm["topics"]

    errors = (
        await db.execute(select(ErrorRecord).where(ErrorRecord.student_user_id == student_id))
    ).scalars().all()
    # حل‌نشده = باز یا در چرخه ترمیم یا بازگشته
    open_errors = [e for e in errors if e.status in ("open", "in_remediation", "relapsed")]

    weak_topics = []
    for st in pm["states"]:
        k = status_of(st.effective_mastery, st.evidence_count)
        if k in ("weak", "critical") and len(weak_topics) < 5 and st.topic_id in topics:
            weak_topics.append({"topic_id": st.topic_id, "title": topics[st.topic_id].title_fa, "status": k})

    gap = pm["gap"]
    advice = None
    if abs(gap) >= 15 and gap > 0:
        advice = "خوانده ولی جا نیفتاده — مرور فاصله‌دار و بسته ترمیمی اولویت دارد."
    elif abs(gap) >= 15 and gap < 0:
        advice = "تسلط بالاست ولی عقب‌ماندگی برنامه داریم — سرعت پیشروی بررسی شود."
    elif open_errors:
        advice = f"{len(open_errors)} خطای باز دارد؛ بازآزمون ترمیمی پیشنهاد می‌شود."

    return {
        "student_id": student_id,
        "progress_pct": pm["progress_pct"],
        "mastery_pct": pm["mastery_pct"],
        "gap": gap,
        "gap_message": advice,
        "errors_total": len(errors),
        "errors_open": len(open_errors),
        "status_counts": pm["status_counts"],
        "weak_topics": weak_topics,
        "note_fa": "مقایسه با دانش‌آموزان دیگر نمایش داده نمی‌شود؛ این نمای انحصاری فرزند شماست.",
    }


# ------------------------------------------------------- سند §3: نمرات آزمون‌ها


@router.get("/children/{student_id}/exam-results")
async def child_exam_results(
    student_id: int,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """نمره، درصد، صحیح/غلط/نزده، نمره منفی و زمان هر آزمون + روند (§3)."""
    await _require_child(db, current.id, student_id)
    return await reports.exam_results(db, student_id)


@router.get("/children/{student_id}/exam-results/{attempt_id}")
async def child_exam_result_detail(
    student_id: int,
    attempt_id: int,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """جزئیات یک نتیجه: وضعیت هر مبحث، نوع خطاها و سؤال‌های نادرست (§3)."""
    await _require_child(db, current.id, student_id)
    try:
        return await reports.exam_result_detail(db, student_id, attempt_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


# --------------------------------------- سند §6/§8: برنامه و تکلیف (فقط‌خواندنی)


@router.get("/children/{student_id}/plan")
async def child_plan(
    student_id: int,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """برنامه/تکلیف فقط‌خواندنی + موعدها + بازه‌ی آزمون پیش رو (§6، §8)."""
    await _require_child(db, current.id, student_id)
    return await reports.plan_view(db, student_id)


# ------------------------------------------------- سند §13: هشدار هوشمند والد


@router.get("/children/{student_id}/alerts")
async def child_alerts(
    student_id: int,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """هشدارهای قاعده‌محور والد — فقط سیگنال‌های خودِ فرزند، بدون مقایسه (§13)."""
    await _require_child(db, current.id, student_id)
    alerts = await reports.build_alerts(db, student_id)
    return {
        "student_id": student_id,
        "alerts": alerts,
        "counts": {
            "danger": sum(1 for a in alerts if a["severity"] == "danger"),
            "warning": sum(1 for a in alerts if a["severity"] == "warning"),
            "info": sum(1 for a in alerts if a["severity"] == "info"),
            "total": len(alerts),
        },
        "thresholds": {
            "gap_units": reports.GAP_ALERT_UNITS,
            "inactive_days": reports.INACTIVE_DAYS,
            "repeat_error_min": reports.REPEAT_ERROR_MIN,
        },
        "note_fa": "هشدارها فقط از داده‌های همین فرزند و با قواعد قطعی ساخته می‌شوند؛ "
        "بدون رتبه و بدون مقایسه با فرزندان دیگر.",
    }


# ------------------------------------------------- سند §14: گزارش هفتگی والد


@router.get("/children/{student_id}/weekly-report")
async def child_weekly_report(
    student_id: int,
    refresh: bool = False,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """گزارش هفتگی تجمیعی فرزند (§14) — کش هفتگیِ idempotent؛ refresh=1 بازسازی."""
    await _require_child(db, current.id, student_id)

    # نخست کش همین هفته را ببین؛ فقط در صورت نبودِ ردیف (یا درخواست تازه‌سازی)
    # گزارش ساخته می‌شود — محاسبه‌ی تکراری انجام نمی‌شود.
    week_start = reports.week_bounds(date.today())[0]
    row = (
        await db.execute(
            select(ParentWeeklyReport).where(
                ParentWeeklyReport.parent_user_id == current.id,
                ParentWeeklyReport.student_user_id == student_id,
                ParentWeeklyReport.week_start == week_start,
            )
        )
    ).scalar_one_or_none()
    if row is not None and not refresh:
        return {**row.payload, "cached": True}

    _week_start, payload = await reports.build_weekly_report(db, student_id)
    generated_at = datetime.fromisoformat(payload["generated_at"])
    if row is None:
        db.add(
            ParentWeeklyReport(
                parent_user_id=current.id,
                student_user_id=student_id,
                week_start=week_start,
                generated_at=generated_at,
                payload=payload,
            )
        )
    else:
        row.payload = payload
        row.generated_at = generated_at

    # تنها تغییر وضعیتِ این بخش: ساخت/تازه‌سازی گزارش ⇒ ثبت ممیزی (§ضمیمه ب)
    await log_action(
        db,
        actor_user_id=current.id,
        action="weekly_report_generated",
        entity_type="student",
        entity_id=student_id,
        detail=f"week={week_start.isoformat()} refresh={int(refresh)}",
    )
    await db.commit()
    return {**payload, "cached": False}
