"""District admin APIs (district spec §1-§4, §12, §15): مدارس ناحیه، ثبت
مدرسه، تغییر وضعیت/مدیر مدرسه، کارکنان ناحیه، نمای کلان و درخواست‌های
 استخدام — همه محدود به District Scope تماس‌گیرنده (§33)."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthUser, get_current_user, require_permission
from app.core.db import get_db
from app.core.passwords import hash_password
from app.models.employment import EmploymentRequest
from app.models.org import District, Employee, Employment, School, SchoolAssignment, User
from app.models.rbac import Permission, Role, RolePermission
from app.services import district as district_svc
from app.services.rbac_service import (
    check_delegation_scope,
    grant_permission,
    has_permission_in_scope,
    log_action,
)

router = APIRouter(prefix="/district", tags=["district"])

# نقش‌های مجاز برای ساخت کارمند ناحیه
STAFF_ROLES = {"district_admin", "district_staff", "teacher"}

# مجوزهای پیش‌فرض مدیر ناحیه هنگام ساخت با role=district_admin
DISTRICT_ADMIN_PERMISSIONS = [
    "view_district_analytics",
    "view_school_analytics",
    "manage_employment",
    "manage_permissions",
    "manage_deputies",
    "manage_schools",
    "manage_principals",
    "manage_district_staff",
    "manage_employment_policy",
]


def district_scope(permission_key: str):
    """گارد ناحیه‌ای: کلید مجوز + ناحیه مبدأ تماس‌گیرنده + پوشش حوزه ناحیه
    (نقش بدون محدوده معنا ندارد — district spec §1). شناسه ناحیه را برمی‌گرداند."""

    async def _dep(
        current: AuthUser = Depends(require_permission(permission_key)),
        db: AsyncSession = Depends(get_db),
    ) -> int:
        district_id = await district_svc.caller_district_id(db, current.id)
        if district_id is None:
            raise HTTPException(403, "ناحیه‌ای برای شما تعیین نشده است")
        if not await has_permission_in_scope(db, current.id, permission_key, "district", district_id):
            raise HTTPException(403, f"دسترسی لازم در حوزه ناحیه: {permission_key}")
        return district_id

    return _dep


async def _district_school_or_404(db: AsyncSession, school_id: int, district_id: int) -> School:
    school = await db.get(School, school_id)
    if school is None or school.district_id != district_id:
        raise HTTPException(404, "مدرسه در ناحیه شما یافت نشد")
    return school


# ------------------------- مدارس ناحیه (§4) -------------------------


@router.get("/me/schools")
async def my_schools(
    district_id: int = Depends(district_scope("view_district_analytics")),
    status: str | None = None,
    search: str | None = None,
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
):
    """مدارس ناحیه تماس‌گیرنده با تجمیع هر مدرسه (دانش‌آموز، تسطّل با رعایت
    حداقل جمعیت، وضعیت) + فیلتر وضعیت و جست‌وجو."""
    schools = await district_svc.district_schools(db, district_id)
    rows = []
    for school in schools:
        if status is not None and school.status != status:
            continue
        if search is not None and search.strip():
            needle = search.strip()
            if needle not in school.name and needle not in school.school_code:
                continue
        rows.append(await district_svc.school_row(db, school))
    district = await db.get(District, district_id)
    return {
        "district": {"id": district_id, "name": district.name if district else None},
        "total": len(rows),
        "schools": rows,
    }


class SchoolIn(BaseModel):
    school_code: str
    name: str
    school_type: str
    ownership_type: str
    address: str | None = None


@router.post("/schools")
async def register_school(
    body: SchoolIn,
    district_id: int = Depends(district_scope("manage_schools")),
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
):
    """ثبت مدرسه جدید در ناحیه تماس‌گیرنده (رویداد school_registered)."""
    if not body.school_code.strip() or not body.name.strip():
        raise HTTPException(400, "کد و نام مدرسه الزامی است")
    duplicate = (
        await db.execute(select(School.id).where(School.school_code == body.school_code.strip()))
    ).first()
    if duplicate is not None:
        raise HTTPException(400, "کد مدرسه تکراری است")
    district = await db.get(District, district_id)
    if district is None:
        raise HTTPException(404, "ناحیه یافت نشد")
    school = School(
        district_id=district_id,
        province_id=district.province_id,
        name=body.name.strip(),
        school_code=body.school_code.strip(),
        school_type=body.school_type,
        ownership_type=body.ownership_type,
        address=body.address,
    )
    db.add(school)
    await db.flush()
    await log_action(
        db,
        actor_user_id=current.id,
        action="school_registered",
        entity_type="school",
        entity_id=school.id,
        detail=f"code={school.school_code} district={district_id}",
    )
    await db.commit()
    return {"ok": True, "school": await district_svc.school_row(db, school)}


class SchoolPatchIn(BaseModel):
    status: str | None = None
    name: str | None = None


@router.patch("/schools/{school_id}")
async def update_school(
    school_id: int,
    body: SchoolPatchIn,
    district_id: int = Depends(district_scope("manage_schools")),
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
):
    """فعال/غیرفعال کردن مدرسه (و اصلاح نام) — فقط مدارس همین ناحیه."""
    school = await _district_school_or_404(db, school_id, district_id)
    if body.status is not None:
        if body.status not in ("active", "inactive"):
            raise HTTPException(400, "وضعیت نامعتبر است (active | inactive)")
        school.status = body.status
    if body.name is not None:
        if not body.name.strip():
            raise HTTPException(400, "نام مدرسه نمی‌تواند خالی باشد")
        school.name = body.name.strip()
    await db.commit()
    return {"ok": True, "school": await district_svc.school_row(db, school)}


class PrincipalIn(BaseModel):
    user_id: int


@router.post("/schools/{school_id}/principal")
async def appoint_principal(
    school_id: int,
    body: PrincipalIn,
    district_id: int = Depends(district_scope("manage_principals")),
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
):
    """انتصاب/تغییر مدیر مدرسه (district spec §15): مدیر قبلی با امروز بسته
    می‌شود (principal_changed)، مدیر جدید ساخته می‌شود (principal_assigned)."""
    school = await _district_school_or_404(db, school_id, district_id)
    user = await db.get(User, body.user_id)
    if user is None or not user.is_active:
        raise HTTPException(404, "کاربر یافت نشد")

    employee = (
        await db.execute(select(Employee).where(Employee.user_id == user.id))
    ).scalar_one_or_none()
    if employee is None:
        employee = Employee(user_id=user.id)
        db.add(employee)
        await db.flush()

    active_old = (
        await db.execute(
            select(SchoolAssignment).where(
                SchoolAssignment.school_id == school_id,
                SchoolAssignment.role == "principal",
                SchoolAssignment.status == "active",
            )
        )
    ).scalars().all()
    if any(a.employee_id == employee.id for a in active_old):
        return {"ok": True, "changed": False, "school_id": school_id, "principal_user_id": user.id}

    for old in active_old:
        old_employee = await db.get(Employee, old.employee_id)
        old_user_id = old_employee.user_id if old_employee else None
        old.end_date = date.today()
        old.status = "ended"
        await log_action(
            db,
            actor_user_id=current.id,
            action="principal_changed",
            entity_type="school",
            entity_id=school_id,
            detail=f"old_user={old_user_id} new_user={user.id} assignment={old.id}",
        )

    assignment = SchoolAssignment(
        employee_id=employee.id,
        school_id=school_id,
        role="principal",
        start_date=date.today(),
        status="active",
    )
    db.add(assignment)
    await db.flush()
    await log_action(
        db,
        actor_user_id=current.id,
        action="principal_assigned",
        entity_type="school",
        entity_id=school_id,
        detail=f"user={user.id} assignment={assignment.id}",
    )
    await log_action(
        db,
        actor_user_id=current.id,
        action="school_assignment_created",
        entity_type="school_assignment",
        entity_id=assignment.id,
        detail=f"school={school_id} role=principal user={user.id}",
    )
    await db.commit()
    return {
        "ok": True,
        "changed": True,
        "school_id": school_id,
        "principal_user_id": user.id,
        "assignment_id": assignment.id,
    }


# ------------------------- کارکنان ناحیه (§12) -------------------------


@router.get("/staff")
async def list_staff(
    district_id: int = Depends(district_scope("manage_district_staff")),
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
):
    return {"district_id": district_id, "staff": await district_svc.district_staff(db, district_id)}


class StaffIn(BaseModel):
    username: str
    password: str
    full_name: str
    role: str
    permission_keys: list[str] | None = None


async def _grant_role_for(db: AsyncSession, keys: list[str]) -> Role | None:
    """نقشی که همه کلیدها را دارد (ترجیح: district_admin) — کلیدهای هر نقش
    با یک کوئری صریح خوانده می‌شوند (بارگذاری تنبل در async ممنوع)."""
    rows = (
        await db.execute(
            select(Role.id, Role.key, Permission.key)
            .join(RolePermission, RolePermission.role_id == Role.id)
            .join(Permission, Permission.id == RolePermission.permission_id)
        )
    ).all()
    by_role: dict[int, tuple[str, set[str]]] = {}
    for role_id, role_key, perm_key in rows:
        entry = by_role.setdefault(role_id, (role_key, set()))
        entry[1].add(perm_key)
    ordered = sorted(by_role.items(), key=lambda item: item[1][0] != "district_admin")
    for role_id, (_, role_keys) in ordered:
        if all(key in role_keys for key in keys):
            return await db.get(Role, role_id)
    return None


@router.post("/staff")
async def create_staff(
    body: StaffIn,
    district_id: int = Depends(district_scope("manage_district_staff")),
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
):
    """ساخت کارمند ناحیه: User + Employee + Employment(official, org=district)
    + (اختیاری) بسته مجوزها با حوزه ناحیه از طریق rbac_service — هنگام ساخت
    مدیر ناحیه رویداد district_admin_assigned ثبت می‌شود."""
    if body.role not in STAFF_ROLES:
        raise HTTPException(400, f"نقش نامعتبر است ({', '.join(sorted(STAFF_ROLES))})")
    if len(body.password) < 6:
        raise HTTPException(400, "رمز عبور باید حداقل ۶ نویسه باشد")
    if not body.full_name.strip():
        raise HTTPException(400, "نام کامل الزامی است")
    if (await db.execute(select(User.id).where(User.username == body.username))).first() is not None:
        raise HTTPException(400, "نام کاربری تکراری است")
    district = await db.get(District, district_id)
    if district is None:
        raise HTTPException(404, "ناحیه یافت نشد")

    keys = body.permission_keys
    if keys is None:
        keys = list(DISTRICT_ADMIN_PERMISSIONS) if body.role == "district_admin" else []
    for key in keys:
        if (await db.execute(select(Permission.id).where(Permission.key == key))).first() is None:
            raise HTTPException(400, f"مجوز نامعتبر: {key}")
    role = await _grant_role_for(db, keys) if keys else None
    if keys and role is None:
        raise HTTPException(400, "هیچ نقشی این مجوزها را ندارد")

    # پیش‌بررسی قاعده طلایی — پیش از ایجاد کاربر
    for key in keys:
        check = await check_delegation_scope(
            db,
            grantor_user_id=current.id,
            grantee_user_id=None,
            permission_key=key,
            scope_type="district",
            scope_id=district_id,
        )
        if not check["ok"]:
            await db.commit()  # لاگ ردّ تفویض پایدار بماند
            raise HTTPException(403, detail=check["reason"])

    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        full_name=body.full_name.strip(),
        system_role=body.role,
    )
    db.add(user)
    await db.flush()
    employee = Employee(user_id=user.id)
    db.add(employee)
    await db.flush()
    db.add(
        Employment(
            employee_id=employee.id,
            employment_type="official",
            organization="district",
            district_id=district_id,
            start_date=date.today(),
            status="active",
        )
    )
    await db.flush()

    granted: list[str] = []
    for key in keys:
        permission = (await db.execute(select(Permission).where(Permission.key == key))).scalar_one_or_none()
        result = await grant_permission(
            db,
            grantor_user_id=current.id,
            grantee_user_id=user.id,
            role_id=role.id,
            permission_id=permission.id,
            scope_type="district",
            scope_id=district_id,
        )
        if not result.get("ok"):
            await db.commit()
            raise HTTPException(403, detail=result["reason"])
        granted.append(key)

    if body.role == "district_admin":
        await log_action(
            db,
            actor_user_id=current.id,
            action="district_admin_assigned",
            entity_type="user",
            entity_id=user.id,
            detail=f"district={district_id} granted={','.join(granted)}",
        )
    await db.commit()
    return {"ok": True, "user_id": user.id, "granted": granted}


# ------------------------- نمای کلان و استخدام -------------------------


@router.get("/overview")
async def overview(
    district_id: int = Depends(district_scope("view_district_analytics")),
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
):
    """نمای کلان ناحیه: وضعیت آموزشی تجمیعی، شمارش‌ها و ضعیف‌ترین مباحث."""
    return await district_svc.overview(db, district_id)


@router.get("/employment-requests")
async def employment_requests(
    district_id: int = Depends(district_scope("manage_employment")),
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
):
    """درخواست‌های استخدام مدارس همین ناحیه (فیلتر اختیاری وضعیت).
    تصمیم‌گیری از همان endpoint موجود /admin/.../decide انجام می‌شود که
    حالا حوزه ناحیه را چک می‌کند."""
    schools = await district_svc.district_schools(db, district_id)
    school_ids = [sc.id for sc in schools]
    rows = (
        await db.execute(
            select(EmploymentRequest)
            .where(EmploymentRequest.school_id.in_(school_ids))
            .order_by(EmploymentRequest.created_at.desc())
        )
    ).scalars().all() if school_ids else []
    if status is not None:
        rows = [r for r in rows if r.status == status]
    return {
        "district_id": district_id,
        "requests": [
            {
                "id": r.id,
                "school_id": r.school_id,
                "full_name": r.full_name,
                "employment_type": r.employment_type,
                "organization": r.organization,
                "subject": r.subject,
                "status": r.status,
                "created_at": r.created_at,
            }
            for r in rows
        ],
    }
