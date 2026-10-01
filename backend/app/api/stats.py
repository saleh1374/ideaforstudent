"""Province / ministry APIs (roadmap phase 7): تجمیع‌های province /
national_topic_stats + نمای کلان — با قاعده حداقل جمعیت ۱۰ + حوزه تماس‌گیرنده
(/geo/me برای پنل استان در فرانت‌اند)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthUser, get_current_user, require_permission
from app.core.db import get_db
from app.models.org import ClassRoom, District, Employee, Province, School, SchoolAssignment
from app.services import insights, stats_service
from app.services.rbac_service import user_scopes

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
