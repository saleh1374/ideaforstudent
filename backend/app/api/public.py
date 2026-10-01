"""عمومی‌ترین endpointها (بدون احراز هویت) — فهرست مدارس برای انتخابگر
فرم ثبت‌نام عمومی دانش‌آموز (Feature B)."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.org import District, School

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/schools")
async def public_schools(db: AsyncSession = Depends(get_db)):
    """فهرست مدارس برای «مدرسه را انتخاب کنید» در ثبت‌نام — عمومی، بدون توکن."""
    rows = (
        await db.execute(
            select(School, District.name)
            .join(District, District.id == School.district_id)
            .order_by(School.id)
        )
    ).all()
    return [
        {
            "id": school.id,
            "name": school.name,
            "school_type": school.school_type,
            "district_name": district_name,
        }
        for school, district_name in rows
    ]
