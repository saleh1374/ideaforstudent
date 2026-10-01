"""Province / ministry APIs (roadmap phase 7): تجمیع‌های province /
national_topic_stats + نمای کلان — با قاعده حداقل جمعیت ۱۰."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthUser, require_permission
from app.core.db import get_db
from app.models.org import Province
from app.services import stats_service

router = APIRouter(prefix="/geo", tags=["province", "ministry"])


@router.get("/province/{province_id}/overview")
async def province_overview(
    province_id: int,
    current: AuthUser = Depends(require_permission("view_province_analytics")),
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
    current: AuthUser = Depends(require_permission("view_province_analytics")),
    db: AsyncSession = Depends(get_db),
):
    if await db.get(Province, province_id) is None:
        raise HTTPException(404, "استان یافت نشد")
    result = await stats_service.topic_stats(db, province_id)
    await db.commit()  # در صورت بازمحاسبه اولیه، تجمیع‌ها ذخیره شوند
    return result


@router.get("/national/overview")
async def national_overview(
    current: AuthUser = Depends(require_permission("view_national_analytics")),
    db: AsyncSession = Depends(get_db),
):
    result = await stats_service.overview(db, None)
    await db.commit()
    return result


@router.get("/national/topics")
async def national_topics(
    current: AuthUser = Depends(require_permission("view_national_analytics")),
    db: AsyncSession = Depends(get_db),
):
    result = await stats_service.topic_stats(db, None)
    await db.commit()
    return result


@router.post("/national/refresh")
async def national_refresh(
    current: AuthUser = Depends(require_permission("view_national_analytics")),
    db: AsyncSession = Depends(get_db),
):
    """بازمحاسبه تجمیع‌های ملی + همه استان‌ها (قابل اجرا توسط وزارت/استان)."""
    national = await stats_service.recompute_topic_stats(db, None)
    provinces = (await db.execute(select(Province))).scalars().all()
    per_province = [await stats_service.recompute_topic_stats(db, p.id) for p in provinces]
    await db.commit()
    return {"national": national, "provinces": per_province}
