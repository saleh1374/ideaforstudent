"""Province / ministry APIs (roadmap phase 7): تجمیع‌های province /
national_topic_stats + نمای کلان — با قاعده حداقل جمعیت ۱۰ + حوزه تماس‌گیرنده
(/geo/me برای پنل استان در فرانت‌اند)."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthUser, get_current_user, require_permission
from app.core.db import get_db
from app.models.district_reports import DistrictReport  # noqa: F401  (register tables)
from app.models.org import ClassRoom, District, Employee, Province, School, SchoolAssignment
from app.services import insights, stats_service
from app.services.rbac_service import log_action, user_scopes

router = APIRouter(prefix="/geo", tags=["province", "ministry"])


@router.get("/me")
async def geo_me(
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """حوزه جغرافیایی تماس‌گیرنده (فقط احراز هویت، هر نقشی): از تخصیص‌های
    مجوز فعال (PermissionAssignment) و در نبود آن، از تخصیص مدرسه‌اش استخراج
    می‌شود — موتور مسیر /province در فرانت‌اند (استان → ناحیه → مدرسه)."""
    scopes = set(await user_scopes(db, current.id))
    province_id: int | None = None
    district_id: int | None = None

    # ۱) حوزه‌های صریح مجوز: province / district
    for scope_type, scope_id in sorted(scopes):
        if scope_type == "province" and province_id is None:
            province_id = scope_id
        elif scope_type == "district" and district_id is None:
            district_id = scope_id

    # ۲) مدرسه/کلاسِ حوزه‌مند → استان و ناحیه مدرسه
    school_ids = [scope_id for scope_type, scope_id in scopes if scope_type == "school"]
    for scope_type, scope_id in scopes:
        if scope_type == "class":
            class_room = await db.get(ClassRoom, scope_id)
            if class_room is not None:
                school_ids.append(class_room.school_id)

    # ۳) در نبود هر دو: آخرین تخصیص فعال مدرسه (مثلاً مدیر/معلم مدرسه)
    if not school_ids and (province_id is None or district_id is None):
        rows = (
            await db.execute(
                select(SchoolAssignment.school_id)
                .join(Employee, Employee.id == SchoolAssignment.employee_id)
                .where(Employee.user_id == current.id, SchoolAssignment.status == "active")
                .order_by(SchoolAssignment.id)
            )
        ).all()
        school_ids = [school_id for (school_id,) in rows]

    for school_id in sorted(set(school_ids)):
        school = await db.get(School, school_id)
        if school is None:
            continue
        if province_id is None:
            province_id = school.province_id
        if district_id is None:
            district_id = school.district_id
        if province_id is not None and district_id is not None:
            break

    # ۴) فقط حوزه ناحیه داریم → استان از همان ناحیه
    if province_id is None and district_id is not None:
        district = await db.get(District, district_id)
        if district is not None:
            province_id = district.province_id

    return {"province_id": province_id, "district_id": district_id, "role": current.system_role}


@router.get("/province/{province_id}/overview")
async def province_overview(
    province_id: int,
    current: AuthUser = Depends(require_permission("view_province_analytics", scope_type="province", scope_param="province_id")),
    db: AsyncSession = Depends(get_db),
):
    if await db.get(Province, province_id) is None:
        raise HTTPException(404, "استان یافت نشد")
    result = await stats_service.overview(db, province_id)
    await db.commit()
    return result


@router.get("/province/{province_id}/topics")
async def province_topics(
    province_id: int,
    current: AuthUser = Depends(require_permission("view_province_analytics", scope_type="province", scope_param="province_id")),
    db: AsyncSession = Depends(get_db),
):
    if await db.get(Province, province_id) is None:
        raise HTTPException(404, "استان یافت نشد")
    result = await stats_service.topic_stats(db, province_id)
    await db.commit()  # در صورت بازمحاسبه اولیه، تجمیع‌ها ذخیره شوند
    return result


@router.get("/province/{province_id}/insights")
async def province_insights(
    province_id: int,
    current: AuthUser = Depends(require_permission("view_province_analytics", scope_type="province", scope_param="province_id")),
    db: AsyncSession = Depends(get_db),
):
    """روایت نقاط ضعف استان (تحلیل قاعده‌محور) — حوزه مجوز باید همین
    استان را بپوشاند؛ استانِ دیگر 403 و بدون هیچ عدد سرکوب‌شده‌ای."""
    if await db.get(Province, province_id) is None:
        raise HTTPException(404, "استان یافت نشد")
    result = await insights.province_insights(db, province_id)
    await db.commit()  # در صورت بازمحاسبه اولیه تجمیع‌ها ذخیره شوند
    return result


@router.get("/national/overview")
async def national_overview(
    current: AuthUser = Depends(require_permission("view_national_analytics", scope_type="national", scope_id=0)),
    db: AsyncSession = Depends(get_db),
):
    result = await stats_service.overview(db, None)
    await db.commit()
    return result


@router.get("/national/topics")
async def national_topics(
    current: AuthUser = Depends(require_permission("view_national_analytics", scope_type="national", scope_id=0)),
    db: AsyncSession = Depends(get_db),
):
    result = await stats_service.topic_stats(db, None)
    await db.commit()
    return result


@router.get("/national/insights")
async def national_insights(
    current: AuthUser = Depends(require_permission("view_national_analytics", scope_type="national", scope_id=0)),
    db: AsyncSession = Depends(get_db),
):
    """روایت نقاط ضعف کشور + رتب‌بندی استان‌ها (بدون اعداد سرکوب‌شده) —
    فقط حوزه national (وزارت یا استان دارای مجوز کشوری)."""
    result = await insights.national_insights(db)
    await db.commit()  # در صورت بازمحاسبه اولیه تجمیع‌ها ذخیره شوند
    return result


@router.post("/national/refresh")
async def national_refresh(
    current: AuthUser = Depends(require_permission("view_national_analytics", scope_type="national", scope_id=0)),
    db: AsyncSession = Depends(get_db),
):
    """بازمحاسبه تجمیع‌های ملی + همه استان‌ها (قابل اجرا توسط وزارت/استان)."""
    national = await stats_service.recompute_topic_stats(db, None)
    provinces = (await db.execute(select(Province))).scalars().all()
    per_province = [await stats_service.recompute_topic_stats(db, p.id) for p in provinces]
    await db.commit()
    return {"national": national, "provinces": per_province}


# ------------- §32 دریافت گزارش ناحیه‌ها در پنل استان -------------

REPORT_STATUS_FA = {
    "draft": "پیش‌نویس",
    "submitted": "ارسال‌شده به استان",
    "reviewed": "در حال بازبینی",
    "returned": "برگشت‌خورده",
    "approved": "تأییدشده",
}


@router.get("/province/{province_id}/district-reports")
async def province_district_reports(
    province_id: int,
    status: str | None = None,
    current: AuthUser = Depends(require_permission("view_province_analytics", scope_type="province", scope_param="province_id")),
    db: AsyncSession = Depends(get_db),
):
    """گزارش‌های ارسال‌شده ناحیه‌های این استان (§32) — فقط ناحیه‌های همین
    استان؛ فیلتر اختیاری وضعیت."""
    if await db.get(Province, province_id) is None:
        raise HTTPException(404, "استان یافت نشد")
    district_ids = [
        d.id
        for d in (
            (await db.execute(select(District).where(District.province_id == province_id))).scalars()
        )
    ]
    rows = (
        await db.execute(
            select(DistrictReport)
            .where(DistrictReport.district_id.in_(district_ids))
            .order_by(DistrictReport.created_at.desc())
        )
    ).scalars().all() if district_ids else []
    if status is not None:
        rows = [r for r in rows if r.status == status]
    names = {
        d.id: d.name
        for d in ((await db.execute(select(District).where(District.id.in_(district_ids)))).scalars()
                  if district_ids else [])
    }
    return {
        "province_id": province_id,
        "total": len(rows),
        "reports": [
            {
                "id": r.id,
                "district_id": r.district_id,
                "district_name": names.get(r.district_id),
                "title_fa": r.title_fa,
                "period_start": r.period_start.isoformat(),
                "period_end": r.period_end.isoformat(),
                "status": r.status,
                "status_fa": REPORT_STATUS_FA.get(r.status, r.status),
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
                "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None,
                "review_note": r.review_note,
            }
            for r in rows
        ],
    }


class ReportDecisionIn(BaseModel):
    decision: str  # return | approve
    note_fa: str | None = None


@router.post("/province/{province_id}/district-reports/{report_id}/decision")
async def province_district_report_decision(
    province_id: int,
    report_id: int,
    body: ReportDecisionIn,
    current: AuthUser = Depends(require_permission("view_province_analytics", scope_type="province", scope_param="province_id")),
    db: AsyncSession = Depends(get_db),
):
    """تصمیم استان روی گزارش ناحیه (§32): برگشت برای اصلاح (returned) یا
    تأیید (approved) — با ممیزی province_report_returned / approved."""
    if await db.get(Province, province_id) is None:
        raise HTTPException(404, "استان یافت نشد")
    report = await db.get(DistrictReport, report_id)
    if report is None:
        raise HTTPException(404, "گزارش یافت نشد")
    district = await db.get(District, report.district_id)
    if district is None or district.province_id != province_id:
        raise HTTPException(404, "گزارش متعلق به ناحیه‌ای در این استان نیست")
    if report.status != "submitted":
        raise HTTPException(409, "فقط گزارش ارسال‌شده قابل بررسی است")
    if body.decision not in ("return", "approve"):
        raise HTTPException(400, "تصمیم نامعتبر است (return | approve)")
    if body.decision == "return" and not (body.note_fa or "").strip():
        raise HTTPException(400, "برای برگشت گزارش، دلیل اصلاح الزامی است")

    report.status = "returned" if body.decision == "return" else "approved"
    report.reviewed_by = current.id
    report.reviewed_at = datetime.utcnow()
    report.review_note = (body.note_fa or "").strip() or None
    await log_action(
        db,
        actor_user_id=current.id,
        action="province_report_returned" if body.decision == "return" else "province_report_approved",
        entity_type="district_report",
        entity_id=report.id,
        detail=f"province={province_id} note={report.review_note or '-'}",
    )
    await db.commit()
    return {
        "ok": True,
        "report": {
            "id": report.id,
            "status": report.status,
            "status_fa": REPORT_STATUS_FA.get(report.status, report.status),
            "reviewed_at": report.reviewed_at.isoformat() if report.reviewed_at else None,
            "review_note": report.review_note,
        },
    }
