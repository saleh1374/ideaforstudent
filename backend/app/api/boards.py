"""Boards APIs (roadmap phase 5 «بردها»): مدرسه / استان / کشور — نام مستعار
و حداقل جمعیت ۱۰ نفر؛ زیر حد نصاب عدد نمایش داده نمی‌شود."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthUser, get_current_user
from app.core.db import get_db
from app.services import boards as boards_svc

router = APIRouter(prefix="/boards", tags=["boards"])


@router.get("/school/{school_id}")
async def school_board(
    school_id: int,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await boards_svc.school_board(db, school_id)


@router.get("/province/{province_id}")
async def province_board(
    province_id: int,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await boards_svc.province_board(db, province_id)


@router.get("/national")
async def national_board(
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await boards_svc.national_board(db)


@router.get("/me")
async def my_board(
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """«جایگاه من» (§8.1): سه نما — عملکرد/رشد/تسط + صدک و مقایسهٔ مبحثی."""
    return await boards_svc.student_board(db, current.id)


@router.get("/me/badges")
async def my_badges(
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """نشان‌ها و تقدیر (§8.4) — پاداش رشد و رفتار یادگیری."""
    return await boards_svc.student_badges(db, current.id)
