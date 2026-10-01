"""Auth endpoints (MVP: username login; OTP/SMS comes later) + ثبت‌نام عمومی
دانش‌آموز (Feature B: درخواست ثبت می‌شود، کاربر فقط پس از تأیید ساخته می‌شود)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthUser, get_current_user
from app.core.db import get_db
from app.core.passwords import hash_password
from app.core.security import make_token
from app.models.org import AdmissionRequest, School, User
from app.services import admission as admission_svc
from app.services.rbac_service import log_action

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


@router.post("/login")
async def login(body: LoginIn, db: AsyncSession = Depends(get_db)):
    user = (
        await db.execute(select(User).where(User.username == body.username))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="نام کاربری یا رمز نادرست است")
    # MVP: plain compare against seeded demo password; replace with passlib hash check
    from app.core.passwords import verify_password

    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="نام کاربری یا رمز نادرست است")
    return {"token": make_token(user.id), "user": {"id": user.id, "full_name": user.full_name, "role": user.system_role}}


@router.get("/me")
async def me(current: AuthUser = Depends(get_current_user)):
    return {"id": current.id, "username": current.username, "full_name": current.full_name, "role": current.system_role}


class RegisterIn(BaseModel):
    username: str
    password: str
    full_name: str
    grade: str
    phone: str | None = None
    school_id: int | None = None


@router.post("/register")
async def register(body: RegisterIn, db: AsyncSession = Depends(get_db)):
    """ثبت‌نام عمومی دانش‌آموز — عمومی (بدون توکن): فقط «درخواست» ثبت می‌شود؛
    ردیف User هنگام تأیید مدیر مدرسه ساخته می‌شود، پس هیچ‌کس پیش از تأیید
    نمی‌تواند وارد شود. رمز همین‌جا هش می‌شود تا تأیید فوری باشد."""
    username = body.username.strip()
    if not admission_svc.username_format_ok(username):
        raise HTTPException(400, "نام کاربری نامعتبر است")
    if len(body.password) < 6:
        raise HTTPException(400, "رمز عبور باید حداقل ۶ نویسه باشد")
    if not body.full_name.strip():
        raise HTTPException(400, "نام کامل الزامی است")
    if not admission_svc.grade_ok(body.grade):
        raise HTTPException(400, "پایه تحصیلی نامعتبر است")

    # یکتایی در هر دو جدول: کاربران موجود + درخواست‌های در انتظار
    if await admission_svc.username_taken(db, username):
        raise HTTPException(409, admission_svc.DUP_USERNAME)

    if body.school_id is not None and await db.get(School, body.school_id) is None:
        raise HTTPException(404, "مدرسه یافت نشد")

    req = AdmissionRequest(
        full_name=body.full_name.strip(),
        username=username,
        password_hash=hash_password(body.password),
        grade=body.grade,
        phone=body.phone,
        school_id=body.school_id,
        status="pending",
    )
    db.add(req)
    await db.flush()
    await log_action(
        db,
        actor_user_id=None,  # ثبت‌نام عمومی است — هنوز کاربری وجود ندارد
        action="admission_submitted",
        entity_type="admission_request",
        entity_id=req.id,
        detail=f"username={username} school={body.school_id}",
    )
    await db.commit()
    return {
        "ok": True,
        "message_fa": "درخواست شما ثبت شد و پس از تأیید مدیر مدرسه فعال می‌شود",
        "request_id": req.id,
    }
