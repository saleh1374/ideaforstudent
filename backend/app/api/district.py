"""District admin APIs (district spec §1-§4, §12, §15, §20-§21, §25-§27): مدارس
ناحیه، ثبت مدرسه، تغییر وضعیت/مدیر مدرسه، کارکنان ناحیه، نمای کلان، درخواست‌های
 استخدام، آزمون‌های رسمی ناحیه + تحلیل سؤال، مداخله آموزشی و مأموریت مدارس —
همه محدود به District Scope تماس‌گیرنده (§33)."""
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthUser, get_current_user, require_permission
from app.core.db import get_db
from app.core.passwords import hash_password
from app.models.employment import EmploymentRequest
from app.models.district_exams import DistrictExam  # noqa: F401  (register tables)
from app.models.district_reports import DistrictReport, StudentTransfer  # noqa: F401
from app.models.org import (
    ClassRoom,
    District,
    Employee,
    Employment,
    School,
    SchoolAssignment,
    StudentProfile,
    User,
)
from app.models.rbac import Permission, Role, RolePermission
from app.models.teacher_assessment import TeacherIntervention
from app.services import district as district_svc
from app.services import district_exams as de_svc
from app.services import teacher_qualification as tq_svc
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
    "manage_teacher_qualifications",
    "manage_admissions",  # Feature B: پذیرش ثبت‌نام دانش‌آموزان ناحیه
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


# ------------------- آزمون صلاحیت معلم (سند صلاحیت) -------------------


@router.get("/teachers")
async def district_teachers(
    district_id: int = Depends(district_scope("view_district_analytics")),
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
):
    """معلمان دارای تخصیص فعال در مدرسه‌های ناحیه + وضعیت صلاحیت سال جاری
    (برای انتخاب‌گرها و خلاصه پنل ناحیه)."""
    rows = await tq_svc.district_teachers(db, district_id)
    return {"district_id": district_id, "total": len(rows), "teachers": rows}


class QualificationAssignIn(BaseModel):
    teacher_user_id: int
    subject: str
    school_year: str | None = None


@router.post("/teacher-qualifications/assign")
async def assign_qualification_exams(
    body: QualificationAssignIn,
    district_id: int = Depends(district_scope("manage_teacher_qualifications")),
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
):
    """تخصیص هر دو آزمون صلاحیت (درس + مدیریت کلاس) برای سال تحصیلی —
    idempotent؛ معلم باید همین درس را در مدرسه‌ای از این ناحیه ارائه دهد."""
    school_year = (body.school_year or "").strip() or tq_svc.current_school_year()
    result = await tq_svc.assign_year_exams(
        db,
        teacher_user_id=body.teacher_user_id,
        subject=body.subject,
        school_year=school_year,
        assigned_by=current.id,
        district_id=district_id,
    )
    await db.commit()
    return result


@router.get("/teacher-qualifications")
async def list_qualifications(
    district_id: int = Depends(district_scope("view_district_analytics")),
    status: str | None = None,
    school_id: int | None = None,
    subject: str | None = None,
    school_year: str | None = None,
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
):
    """رکوردهای صلاحیت ناحیه با فیلتر وضعیت/مدرسه/درس/سال + درصد هر آزمون
    و شمار اقدام‌های اصلاحی."""
    rows = await tq_svc.district_qualifications(
        db, district_id, status=status, school_id=school_id, subject=subject, school_year=school_year
    )
    return {
        "district_id": district_id,
        "total": len(rows),
        "qualifications": rows,
    }


@router.get("/teacher-qualifications/{qualification_id}")
async def qualification_detail(
    qualification_id: int,
    district_id: int = Depends(district_scope("view_district_analytics")),
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
):
    """جزئیات رکورد صلاحیت: آزمون‌ها + تلاش‌ها + تاریخچه اقدام‌ها
    (فقط رکوردهای همین ناحیه؛ خارج از حوزه → 404)."""
    qual = await tq_svc.district_qualification_or_404(db, qualification_id, district_id)
    return await tq_svc.qualification_detail(db, qual)


class InterventionIn(BaseModel):
    type: str  # training | mentoring | replacement
    notes: str | None = None


@router.post("/teacher-qualifications/{qualification_id}/interventions")
async def create_intervention(
    qualification_id: int,
    body: InterventionIn,
    district_id: int = Depends(district_scope("manage_teacher_qualifications")),
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
):
    """ثبت اقدام اصلاحی (دوره/سرپرستی/جایگزینی) — فقط برای وضعیت
    آزمایشی یا بحرانی (وگرنه 409) + رویداد teacher_intervention_created."""
    qual = await tq_svc.district_qualification_or_404(db, qualification_id, district_id)
    row = await tq_svc.record_intervention(db, qual, body.type, body.notes, current.id)
    await db.commit()
    return {"ok": True, "intervention": tq_svc.intervention_row(row)}


class InterventionStatusIn(BaseModel):
    status: str  # proposed | scheduled | done | cancelled


@router.post("/teacher-qualifications/{qualification_id}/interventions/{intervention_id}/status")
async def set_intervention_status(
    qualification_id: int,
    intervention_id: int,
    body: InterventionStatusIn,
    district_id: int = Depends(district_scope("manage_teacher_qualifications")),
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
):
    """به‌روزرسانی وضعیت اقدام؛ بسته‌شدن نرم (done/cancelled) با ثبت زمان."""
    qual = await tq_svc.district_qualification_or_404(db, qualification_id, district_id)
    row = await db.get(TeacherIntervention, intervention_id)
    if row is None or row.qualification_id != qual.id:
        raise HTTPException(404, "اقدام اصلاحی یافت نشد")
    row = await tq_svc.update_intervention_status(db, row, body.status)
    await db.commit()
    return {"ok": True, "intervention": tq_svc.intervention_row(row)}


# ------------- آزمون‌های رسمی ناحیه / مداخله / مأموریت (§20–§21, §25–§27) -------------
#
# مجوز خواندن: view_district_analytics (مانند بقیه نمای‌های ناحیه).
# مجوز نوشتن: کلید create_exam از قبل به نقش district_admin در حوزه ناحیه
# تخصیص دارد (scripts/seed.py — فایل مشترک و دست‌نخورده)؛ افزودن کلید مجوز
# تازه نیازمند ویرایش seed مشترک است، پس از همان کلید استفاده می‌شود.
DISTRICT_EXAM_VIEW_PERM = "view_district_analytics"
DISTRICT_EXAM_MANAGE_PERM = "create_exam"


class DistrictExamIn(BaseModel):
    title_fa: str
    grade: str
    subject: str
    school_ids: list[int]
    blueprint: str | None = None
    opens_at: datetime | None = None
    closes_at: datetime | None = None
    item_ids: list[int] | None = None       # سؤال صریح از بانک (خالی → نمونه خودکار)
    item_count: int | None = None           # تعداد نمونه خودکار از بانک


class DistrictExamStatusIn(BaseModel):
    status: str  # draft | published | graded | closed


class InterventionIn(BaseModel):
    title_fa: str
    type: str  # course | supervision | replacement | program
    school_ids: list[int]
    topic_id: int | None = None
    grade: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    before_mastery: float | None = None
    notes: str | None = None


class InterventionPatchIn(BaseModel):
    stage: str | None = None      # after | retention
    mastery: float | None = None
    status: str | None = None     # active | closed | cancelled
    notes: str | None = None


class MissionIn(BaseModel):
    title_fa: str
    goal: str
    topic_id: int
    target_mastery: float
    school_ids: list[int]
    deadline: date | None = None  # پیش‌فرض ~۲ هفته


@router.get("/topics")
async def district_topics(
    district_id: int = Depends(district_scope(DISTRICT_EXAM_VIEW_PERM)),
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
):
    """گزینه‌های مبحث کاتالوگ (برای فرم‌های مداخله/مأموریت/سرفصل آزمون)."""
    return {"district_id": district_id, "topics": await de_svc.topics_options(db)}


@router.post("/exams")
async def create_official_exam(
    body: DistrictExamIn,
    district_id: int = Depends(district_scope(DISTRICT_EXAM_MANAGE_PERM)),
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
):
    """ساخت آزمون رسمی ناحیه (§20): پایه + درس + سرفصل + زمان‌بندی +
    مدارس انتخابی + اقلام سؤال — در وضعیت پیش‌نویس با رویداد ممیزی."""
    exam = await de_svc.create_district_exam(
        db,
        district_id=district_id,
        created_by=current.id,
        title_fa=body.title_fa,
        grade=body.grade,
        subject=body.subject,
        school_ids=body.school_ids,
        blueprint=body.blueprint,
        opens_at=body.opens_at,
        closes_at=body.closes_at,
        item_ids=body.item_ids,
        item_count=body.item_count,
    )
    await db.commit()
    return {"ok": True, "exam": await de_svc.district_exam_detail(db, exam)}


@router.get("/exams")
async def list_official_exams(
    status: str | None = None,
    district_id: int = Depends(district_scope(DISTRICT_EXAM_VIEW_PERM)),
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
):
    """فهرست آزمون‌های رسمی ناحیه (فیلتر اختیاری وضعیت)."""
    rows = await de_svc.list_district_exams(db, district_id, status=status)
    return {"district_id": district_id, "total": len(rows), "exams": rows}


@router.get("/exams/{exam_id}")
async def official_exam_detail(
    exam_id: int,
    district_id: int = Depends(district_scope(DISTRICT_EXAM_VIEW_PERM)),
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
):
    """جزئیات آزمون رسمی: مدارس + اقلام سؤال + شرکت‌کنندگان + گذارهای مجاز."""
    exam = await de_svc.district_exam_or_404(db, exam_id, district_id)
    return {"exam": await de_svc.district_exam_detail(db, exam)}


@router.patch("/exams/{exam_id}/status")
async def change_official_exam_status(
    exam_id: int,
    body: DistrictExamStatusIn,
    district_id: int = Depends(district_scope(DISTRICT_EXAM_MANAGE_PERM)),
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
):
    """گذار وضعیت آزمون رسمی (draft → published → graded → closed) با ثبت
    ممیزی صریح انتشار — «کسی آزمون رسمی را منتشر کرد؟» (§20)."""
    exam = await de_svc.district_exam_or_404(db, exam_id, district_id)
    exam = await de_svc.set_exam_status(db, exam, body.status, current.id)
    await db.commit()
    return {"ok": True, "exam": await de_svc.district_exam_detail(db, exam)}


@router.get("/exams/{exam_id}/results")
async def official_exam_results(
    exam_id: int,
    district_id: int = Depends(district_scope(DISTRICT_EXAM_VIEW_PERM)),
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
):
    """نتایج آزمون رسمی به تفکیک مدرسه/کلاس — با سرکوب حداقل جمعیت (§20/§3)."""
    exam = await de_svc.district_exam_or_404(db, exam_id, district_id)
    return await de_svc.exam_results(db, exam)


@router.get("/exams/{exam_id}/item-analysis")
async def official_exam_item_analysis(
    exam_id: int,
    district_id: int = Depends(district_scope(DISTRICT_EXAM_VIEW_PERM)),
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
):
    """تحلیل سؤال‌های آزمون (§21): درصد پاسخ صحیح، دشواری تجربی، قدرت
    تفکیک، پرتکرارترین گزینه غلط + کج‌فهمی و علامت «نیازمند بازبینی»."""
    exam = await de_svc.district_exam_or_404(db, exam_id, district_id)
    return await de_svc.item_analysis(db, exam)


# ------------------------- §25–§26 مداخله آموزشی -------------------------


@router.post("/interventions")
async def create_district_intervention(
    body: InterventionIn,
    district_id: int = Depends(district_scope(DISTRICT_EXAM_MANAGE_PERM)),
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
):
    """ثبت مداخله آموزشی ناحیه با هدف/نوع/مدارس و اندازه‌گیری «پیش از
    مداخله» (خودکار از تجمیع تسط، یا مقدار صریح)."""
    iv = await de_svc.create_intervention(
        db,
        district_id=district_id,
        created_by=current.id,
        title_fa=body.title_fa,
        type=body.type,
        school_ids=body.school_ids,
        topic_id=body.topic_id,
        grade=body.grade,
        start_date=body.start_date,
        end_date=body.end_date,
        before_mastery=body.before_mastery,
        notes=body.notes,
    )
    await db.commit()
    rows = [r for r in await de_svc.list_interventions(db, district_id) if r["id"] == iv.id]
    return {"ok": True, "intervention": rows[0] if rows else None}


@router.get("/interventions")
async def list_district_interventions(
    district_id: int = Depends(district_scope(DISTRICT_EXAM_VIEW_PERM)),
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
):
    """فهرست مداخله‌ها با «سنجش اثر مداخله» (§26)."""
    rows = await de_svc.list_interventions(db, district_id)
    return {"district_id": district_id, "total": len(rows), "interventions": rows}


@router.patch("/interventions/{intervention_id}")
async def update_district_intervention(
    intervention_id: int,
    body: InterventionPatchIn,
    district_id: int = Depends(district_scope(DISTRICT_EXAM_MANAGE_PERM)),
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
):
    """ثبت مرحله اندازه‌گیری (after/retention) و/یا بستن مداخله — با ممیزی."""
    iv = await de_svc.intervention_or_404(db, intervention_id, district_id)
    if body.stage is not None or body.mastery is not None:
        if body.stage is None or body.mastery is None:
            raise HTTPException(400, "برای ثبت اندازه‌گیری، stage و mastery هر دو لازم است")
        iv = await de_svc.record_intervention_measurement(
            db, iv, stage=body.stage, mastery=body.mastery, actor_id=current.id
        )
    if body.status is not None:
        iv = await de_svc.set_intervention_status(db, iv, body.status, current.id)
    if body.notes is not None:
        iv.notes = body.notes.strip() or None
        await db.flush()
    await db.commit()
    rows = [r for r in await de_svc.list_interventions(db, district_id) if r["id"] == iv.id]
    return {"ok": True, "intervention": rows[0] if rows else None}


# ------------------------- §27 مأموریت برای مدارس -------------------------


@router.post("/missions")
async def create_district_mission(
    body: MissionIn,
    district_id: int = Depends(district_scope(DISTRICT_EXAM_MANAGE_PERM)),
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
):
    """تعریف مأموریت آموزشی برای گروهی از مدارس: هدف مشخص + مبحث + آستانه
    تسط + مهلت (پیش‌فرض ~۲ هفته) — سازنده در ممیزی ثبت می‌شود."""
    mission = await de_svc.create_mission(
        db,
        district_id=district_id,
        created_by=current.id,
        title_fa=body.title_fa,
        goal=body.goal,
        topic_id=body.topic_id,
        target_mastery=body.target_mastery,
        school_ids=body.school_ids,
        deadline=body.deadline,
    )
    await db.commit()
    return {"ok": True, "mission": await de_svc.mission_progress(db, mission)}


@router.get("/missions")
async def list_district_missions(
    district_id: int = Depends(district_scope(DISTRICT_EXAM_VIEW_PERM)),
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
):
    """فهرست مأموریت‌ها با وضعیت کلی و شمارش پیشرفت مدارس."""
    rows = await de_svc.list_missions(db, district_id)
    return {"district_id": district_id, "total": len(rows), "missions": rows}


@router.get("/missions/{mission_id}")
async def district_mission_detail(
    mission_id: int,
    district_id: int = Depends(district_scope(DISTRICT_EXAM_VIEW_PERM)),
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
):
    """داشبورد پیشرفت یک مأموریت: تسط هر مدرسه نسبت به هدف (با سرکوب)."""
    mission = await de_svc.mission_or_404(db, mission_id, district_id)
    return {"mission": await de_svc.mission_progress(db, mission)}


# ------------------------- §5–§6 مقایسه و رشد مدارس -------------------------


@router.get("/schools/compare")
async def compare_schools(
    grade: str | None = None,
    subject: str | None = None,
    district_id: int = Depends(district_scope("view_district_analytics")),
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
):
    """مقایسه مدارس در سه گام «سطح ورودی ← وضعیت فعلی ← میزان رشد» (§5) با
    فیلتر اختیاری پایه/درس و سرکوب حداقل جمعیت زیر ۱۰ نفر."""
    return await district_svc.school_comparison(db, district_id, grade=grade, subject=subject)


@router.get("/schools/growth")
async def growth_schools(
    district_id: int = Depends(district_scope("view_district_analytics")),
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
):
    """وضعیت فعلی در برابر رشد هر مدرسه + سری رشد در طول زمان (§6/§2)."""
    return await district_svc.school_growth(db, district_id)


# ------------------------- §2/§3 روندها و شش محور سلامت -------------------------


@router.get("/trends")
async def district_trends(
    district_id: int = Depends(district_scope("view_district_analytics")),
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
):
    """روندهای داشبورد ناحیه (§2): رشد، تسط، ماندگاری، مشارکت، تکمیل، مداخله."""
    return await district_svc.trends(db, district_id)


@router.get("/health")
async def district_health(
    district_id: int = Depends(district_scope("view_district_analytics")),
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
):
    """شش محور سلامت آموزشی مستقل (§3) — بدون ساخت عدد ساختگی واحد."""
    return await district_svc.health_axes(db, district_id)


# ------------------------- §9/§11/§29/§30 مرکز توجه -------------------------


@router.get("/attention-center")
async def district_attention_center(
    district_id: int = Depends(district_scope("view_district_analytics")),
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
):
    """مرکز توجه ناحیه: مدارس/کلاس‌های نیازمند اقدام، مشکلات مشترک و هشدارها."""
    return await district_svc.attention_center(db, district_id)


# ------------------------- §7/§8/§23 تحلیل خطای ناحیه -------------------------


@router.get("/error-analysis")
async def district_error_analysis(
    district_id: int = Depends(district_scope("view_district_analytics")),
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
):
    """طبقه‌بندی خطاهای ناحیه به تفکیک علت/مدرسه/مبحث (§23) با حداقل جمعیت."""
    return await district_svc.error_analysis(db, district_id)


# ------------------------- §18–§19 انتقال دانش‌آموز -------------------------


class TransferIn(BaseModel):
    student_user_id: int
    to_school_id: int
    reason_fa: str
    effective_date: date | None = None


@router.post("/transfers")
async def transfer_student(
    body: TransferIn,
    district_id: int = Depends(district_scope("manage_schools")),
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
):
    """انتقال دانش‌آموز بین مدارس ناحیه (§19): اعتبارسنجی هر دو مدرسه،
    حفظ سابقه مدرسه/کلاس قبلی، جابه‌جایی پروفایل و ثبت ممیزی
    student_transferred — هیچ داده‌ای حذف نمی‌شود."""
    reason = body.reason_fa.strip()
    if not reason:
        raise HTTPException(400, "دلیل انتقال الزامی است")

    profile = (
        await db.execute(select(StudentProfile).where(StudentProfile.user_id == body.student_user_id))
    ).scalar_one_or_none()
    if profile is None or profile.status != "active":
        raise HTTPException(404, "دانش‌آموز فعال در ناحیه یافت نشد")
    if profile.school_id is None:
        raise HTTPException(400, "دانش‌آموز مدرسه‌ای ندارد")

    from_school = await db.get(School, profile.school_id)
    if from_school is None or from_school.district_id != district_id:
        raise HTTPException(404, "دانش‌آموز در مدرسه‌ای خارج از ناحیه شماست")
    to_school = await _district_school_or_404(db, body.to_school_id, district_id)
    if to_school.id == from_school.id:
        raise HTTPException(400, "مدرسه مبدأ و مقصد یکسان است")
    if to_school.status != "active":
        raise HTTPException(400, "مدرسه مقصد فعال نیست")

    from_class_id = profile.class_id
    # کلاس مقصد: هم‌پایه‌ترین کلاس فعال مدرسه مقصد (وگرنه بدون کلاس)
    target_class = (
        await db.execute(
            select(ClassRoom)
            .where(
                ClassRoom.school_id == to_school.id,
                ClassRoom.grade == profile.grade,
                ClassRoom.status == "active",
            )
            .order_by(ClassRoom.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if target_class is None:
        target_class = (
            await db.execute(
                select(ClassRoom)
                .where(ClassRoom.school_id == to_school.id, ClassRoom.status == "active")
                .order_by(ClassRoom.id)
                .limit(1)
            )
        ).scalar_one_or_none()

    transfer = StudentTransfer(
        district_id=district_id,
        student_user_id=profile.user_id,
        from_school_id=from_school.id,
        to_school_id=to_school.id,
        from_class_id=from_class_id,
        to_class_id=target_class.id if target_class else None,
        reason_fa=reason,
        effective_date=body.effective_date or date.today(),
        status="approved",
        approved_by=current.id,
    )
    db.add(transfer)
    profile.school_id = to_school.id
    profile.class_id = target_class.id if target_class else None
    await db.flush()
    await log_action(
        db,
        actor_user_id=current.id,
        action="student_transferred",
        entity_type="student",
        entity_id=profile.user_id,
        detail=(
            f"from_school={from_school.id} to_school={to_school.id} "
            f"from_class={from_class_id} to_class={profile.class_id} reason={reason}"
        ),
    )
    await db.commit()
    return {
        "ok": True,
        "transfer": {
            "id": transfer.id,
            "student_user_id": profile.user_id,
            "from_school_id": from_school.id,
            "from_school": from_school.name,
            "to_school_id": to_school.id,
            "to_school": to_school.name,
            "from_class_id": from_class_id,
            "to_class_id": profile.class_id,
            "reason_fa": reason,
            "effective_date": transfer.effective_date.isoformat(),
            "status": transfer.status,
        },
    }


@router.get("/transfers")
async def list_transfers(
    district_id: int = Depends(district_scope("view_district_analytics")),
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
):
    """سابقه انتقال‌های ناحیه (§19) — برای شفافیت و ممیزی."""
    rows = (
        await db.execute(
            select(StudentTransfer)
            .where(StudentTransfer.district_id == district_id)
            .order_by(StudentTransfer.created_at.desc())
        )
    ).scalars().all()
    school_ids = {r.from_school_id for r in rows} | {r.to_school_id for r in rows}
    schools = {
        s.id: s.name
        for s in (
            (await db.execute(select(School).where(School.id.in_(school_ids)))).scalars()
            if school_ids
            else []
        )
    }
    users = {
        u.id: u.full_name
        for u in (
            (
                await db.execute(
                    select(User).where(User.id.in_({r.student_user_id for r in rows}))
                )
            ).scalars()
            if rows
            else []
        )
    }
    return {
        "district_id": district_id,
        "total": len(rows),
        "transfers": [
            {
                "id": r.id,
                "student_user_id": r.student_user_id,
                "student_name": users.get(r.student_user_id),
                "from_school_id": r.from_school_id,
                "from_school": schools.get(r.from_school_id),
                "to_school_id": r.to_school_id,
                "to_school": schools.get(r.to_school_id),
                "from_class_id": r.from_class_id,
                "to_class_id": r.to_class_id,
                "reason_fa": r.reason_fa,
                "effective_date": r.effective_date.isoformat(),
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


# ------------------------- §31–§32 گزارش ناحیه و ارسال به استان -------------------------


class ReportGenerateIn(BaseModel):
    title_fa: str
    period_start: date
    period_end: date


@router.post("/reports/generate")
async def generate_district_report(
    body: ReportGenerateIn,
    district_id: int = Depends(district_scope("view_district_analytics")),
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
):
    """ساخت پیش‌نویس گزارش مدیریتی ناحیه (§31) از تجمیع همان داده‌های
    موجود — رویداد district_report_generated ثبت می‌شود."""
    title = body.title_fa.strip()
    if not title:
        raise HTTPException(400, "عنوان گزارش الزامی است")
    if body.period_end < body.period_start:
        raise HTTPException(400, "پایان بازه نمی‌تواند پیش از آغاز آن باشد")
    payload = await district_svc.district_report_payload(
        db, district_id, body.period_start, body.period_end
    )
    report = DistrictReport(
        district_id=district_id,
        title_fa=title,
        period_start=body.period_start,
        period_end=body.period_end,
        status="draft",
        payload=payload,
        created_by=current.id,
    )
    db.add(report)
    await db.flush()
    await log_action(
        db,
        actor_user_id=current.id,
        action="district_report_generated",
        entity_type="district_report",
        entity_id=report.id,
        detail=f"title={title} period={body.period_start.isoformat()}..{body.period_end.isoformat()}",
    )
    await db.commit()
    return {"ok": True, "report": _report_row(report)}


@router.get("/reports")
async def list_district_reports(
    district_id: int = Depends(district_scope("view_district_analytics")),
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
):
    """فهرست گزارش‌های ناحیه با وضعیت گردش کار (§32)."""
    rows = (
        await db.execute(
            select(DistrictReport)
            .where(DistrictReport.district_id == district_id)
            .order_by(DistrictReport.created_at.desc())
        )
    ).scalars().all()
    return {
        "district_id": district_id,
        "total": len(rows),
        "reports": [_report_row(r) for r in rows],
    }


@router.get("/reports/{report_id}")
async def district_report_detail(
    report_id: int,
    district_id: int = Depends(district_scope("view_district_analytics")),
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
):
    """محتوای کامل یک گزارش ناحیه (پیش‌نویس/ارسال‌شده/برگشتی)."""
    report = await _district_report_or_404(db, report_id, district_id)
    row = _report_row(report)
    row["payload"] = report.payload or {}
    return {"report": row}


@router.post("/reports/{report_id}/submit")
async def submit_district_report(
    report_id: int,
    district_id: int = Depends(district_scope("view_district_analytics")),
    db: AsyncSession = Depends(get_db),
    current: AuthUser = Depends(get_current_user),
):
    """ارسال گزارش به استان (§32): draft/returned → submitted + ممیزی
    province_report_submitted؛ پس از ارسال گزارش قفل می‌شود."""
    report = await _district_report_or_404(db, report_id, district_id)
    if report.status not in ("draft", "returned"):
        raise HTTPException(409, "فقط پیش‌نویس یا گزارش برگشت‌خورده قابل ارسال است")
    report.status = "submitted"
    report.submitted_at = datetime.utcnow()
    await log_action(
        db,
        actor_user_id=current.id,
        action="province_report_submitted",
        entity_type="district_report",
        entity_id=report.id,
        detail=f"district={district_id}",
    )
    await db.commit()
    return {"ok": True, "report": _report_row(report)}


def _report_row(report: DistrictReport) -> dict:
    return {
        "id": report.id,
        "district_id": report.district_id,
        "title_fa": report.title_fa,
        "period_start": report.period_start.isoformat(),
        "period_end": report.period_end.isoformat(),
        "status": report.status,
        "status_fa": REPORT_STATUS_FA.get(report.status, report.status),
        "created_at": report.created_at.isoformat() if report.created_at else None,
        "submitted_at": report.submitted_at.isoformat() if report.submitted_at else None,
        "reviewed_at": report.reviewed_at.isoformat() if report.reviewed_at else None,
        "review_note": report.review_note,
    }


REPORT_STATUS_FA = {
    "draft": "پیش‌نویس",
    "submitted": "ارسال‌شده به استان",
    "reviewed": "در حال بازبینی",
    "returned": "برگشت‌خورده",
    "approved": "تأییدشده",
}


async def _district_report_or_404(db: AsyncSession, report_id: int, district_id: int) -> DistrictReport:
    report = await db.get(DistrictReport, report_id)
    if report is None or report.district_id != district_id:
        raise HTTPException(404, "گزارش در ناحیه شما یافت نشد")
    return report
