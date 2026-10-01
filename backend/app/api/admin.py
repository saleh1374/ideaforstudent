"""Admin APIs (school admin spec + district spec + RBAC spec §16-18):
aggregated overviews, employment request inbox with scope filtering,
permission grant/revoke with the golden rule (403 on denial), deputies
(معاونان §6) and teacher transfer (§10)."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthUser, get_current_user, require_permission
from app.core.db import get_db
from app.models.employment import EmploymentPolicyRule, EmploymentRequest
from app.models.org import Employee, School, SchoolAssignment, StudentProfile, User
from app.models.rbac import Deputy, Permission, Role
from app.models.slm import StudentTopicState
from app.services.employment import decide_request, is_principal_of, submit_teacher_request
from app.services.rbac_service import (
    check_delegation_scope,
    covering_grants,
    effective_permissions,
    grant_permission,
    grants_of,
    has_permission_in_scope,
    log_action,
    revoke_permission,
    user_scopes,
    visible_school_ids,
)
from app.services import school as school_svc

router = APIRouter(prefix="/admin", tags=["admin"])

# حوزه‌های مجاز برای عملیات سطح بالا (تأیید استخدام، انتقال، سیاست)
BROAD_SCOPES = ("district", "province", "national")


# ------------------------- تحلیل مدرسه (حوزه‌مند) -------------------------


@router.get("/school/{school_id}/overview")
async def school_overview(
    school_id: int,
    current: AuthUser = Depends(require_permission("view_school_analytics", scope_type="school", scope_param="school_id")),
    db: AsyncSession = Depends(get_db),
):
    """داشبورد کلان مدرسه: میانگین تسلط، نیازمندان مداخله، وضعیت کلاس‌ها.
    همه اعداد از همان هسته SLM تجمیع می‌شوند (spec: «هیچ‌کدام از این پنل‌ها
    لایه داده جدا نمی‌سازند»). حوزه مجوز باید همین مدرسه را بپوشاند."""
    school = await db.get(School, school_id)
    if school is None:
        raise HTTPException(404, "مدرسه یافت نشد")

    profiles = (
        await db.execute(select(StudentProfile).where(StudentProfile.school_id == school_id))
    ).scalars().all()
    student_ids = [p.user_id for p in profiles]

    states = (
        await db.execute(select(StudentTopicState).where(StudentTopicState.student_user_id.in_(student_ids)))
    ).scalars().all() if student_ids else []

    from app.services.slm import status_of

    mastery_values = [st.effective_mastery for st in states if st.evidence_count >= 3]
    avg_mastery = round(sum(mastery_values) / len(mastery_values), 1) if mastery_values else None

    status_counts = {"critical": 0, "weak": 0, "consolidating": 0, "mastered": 0, "unknown": 0}
    for st in states:
        key = status_of(st.effective_mastery, st.evidence_count)
        status_counts[key] = status_counts.get(key, 0) + 1

    return {
        "school": {"id": school.id, "name": school.name, "type": school.school_type, "ownership": school.ownership_type},
        "students_count": len(student_ids),
        "avg_effective_mastery": avg_mastery,
        "needs_intervention": status_counts["critical"] + status_counts["weak"],
        "status_counts": status_counts,
    }


@router.get("/school/{school_id}/classes-compare/{subject}")
async def compare_classes_endpoint(
    school_id: int,
    subject: str,
    current: AuthUser = Depends(require_permission("view_school_analytics", scope_type="school", scope_param="school_id")),
    db: AsyncSession = Depends(get_db),
):
    """§7 مقایسه کلاس‌های یک درس — با جمعیت کم فقط نمایشی است."""
    return await school_svc.compare_classes(db, school_id, subject)


@router.get("/school/{school_id}/attention-flags")
async def attention_flags_endpoint(
    school_id: int,
    current: AuthUser = Depends(require_permission("view_school_analytics", scope_type="school", scope_param="school_id")),
    db: AsyncSession = Depends(get_db),
):
    """§5 سامانه «نیازمند بررسی»: پرچم‌های مشخص، نه رتبه‌بندی معلم."""
    return await school_svc.attention_flags(db, school_id)


@router.get("/school/{school_id}/teachers")
async def teacher_profiles_endpoint(
    school_id: int,
    current: AuthUser = Depends(require_permission("view_school_analytics", scope_type="school", scope_param="school_id")),
    db: AsyncSession = Depends(get_db),
):
    """§4 نمایه سبک معلمان: شاخص عینی آموزشی + رفتاری، بدون امتیاز کل."""
    return await school_svc.teacher_lite_profiles(db, school_id)


@router.get("/classes/{class_id}/diagnosis")
async def class_diagnosis_endpoint(
    class_id: int,
    current: AuthUser = Depends(require_permission("view_school_analytics", scope_type="class", scope_param="class_id")),
    db: AsyncSession = Depends(get_db),
):
    """§6 تشخیص چندعاملی ضعف کلاس — قابل اقدام، نه قضاوت."""
    return await school_svc.multi_factor_diagnosis(db, class_id)


@router.get("/classes/{class_id}/summary")
async def class_summary_endpoint(
    class_id: int,
    current: AuthUser = Depends(require_permission("view_school_analytics", scope_type="class", scope_param="class_id")),
    db: AsyncSession = Depends(get_db),
):
    return await school_svc.class_subject_summary(db, class_id)


# ------------------------- گردش کار استخدام (حوزه‌مند) -------------------------


@router.get("/employment-requests")
async def list_employment_requests(
    current: AuthUser = Depends(require_permission("manage_employment")),
    db: AsyncSession = Depends(get_db),
):
    """فقط درخواست‌های مدارسِ در حوزه دید تماس‌گیرنده (مدیر ناحیه ناحیه خودش
    را می‌بیند — district spec §33 دسترسی مبتنی بر محدوده)."""
    rows = (
        await db.execute(select(EmploymentRequest).order_by(EmploymentRequest.created_at.desc()))
    ).scalars().all()
    visible = await visible_school_ids(db, current.id, "manage_employment")
    if visible is not None:
        rows = [r for r in rows if r.school_id in visible]
    return {
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
        ]
    }


class TeacherRequestIn(BaseModel):
    school_id: int
    employee_user_id: int
    full_name: str
    employment_type: str
    organization: str = "government"
    subject: str | None = None


@router.post("/employment-requests")
async def create_teacher_request(
    body: TeacherRequestIn,
    current: AuthUser = Depends(require_permission("manage_employment")),
    db: AsyncSession = Depends(get_db),
):
    """ثبت فقط توسط مدیر همان مدرسه (principal فعال) یا دارنده حوزه
    ناحیه/استان روی آن مدرسه (RBAC spec §5 + district spec §14)."""
    school = await db.get(School, body.school_id)
    if school is None:
        raise HTTPException(404, "مدرسه یافت نشد")
    if not await is_principal_of(db, current.id, body.school_id):
        grants = await covering_grants(db, current.id, "manage_employment", "school", body.school_id)
        if not any(scope_type in BROAD_SCOPES for scope_type, _ in grants):
            raise HTTPException(
                403, "ثبت درخواست استخدام فقط برای مدیر همان مدرسه یا مسئول ناحیه/استان مجاز است"
            )
    result = await submit_teacher_request(
        db,
        school_id=body.school_id,
        requested_by=current.id,
        employee_user_id=body.employee_user_id,
        full_name=body.full_name,
        employment_type=body.employment_type,
        organization=body.organization,
        subject=body.subject,
    )
    if not result.get("ok"):
        raise HTTPException(400, detail=result.get("reason") or "خطا در ثبت درخواست")
    await db.commit()
    return result


class DecisionIn(BaseModel):
    approve: bool
    note: str | None = None


@router.post("/employment-requests/{request_id}/decide")
async def decide_employment_request(
    request_id: int,
    body: DecisionIn,
    current: AuthUser = Depends(require_permission("manage_employment")),
    db: AsyncSession = Depends(get_db),
):
    """تصمیم فقط با حوزه ناحیه/استان/کشور روی مدرسه درخواست — مدیر مدرسه
    (که او هم manage_employment دارد) نمی‌تواند درخواست خودش را تأیید کند."""
    req = await db.get(EmploymentRequest, request_id)
    if req is not None:
        grants = await covering_grants(db, current.id, "manage_employment", "school", req.school_id)
        if not any(scope_type in BROAD_SCOPES for scope_type, _ in grants):
            raise HTTPException(403, "تأیید/رد درخواست استخدام فقط در سطح ناحیه یا بالاتر مجاز است")
    result = await decide_request(db, decider_user_id=current.id, request_id=request_id, approve=body.approve, note=body.note)
    await db.commit()
    return result


@router.get("/employment-policy")
async def get_policy(current: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(EmploymentPolicyRule))).scalars().all()
    return {
        "rules": [
            {
                "id": r.id,
                "school_ownership": r.school_ownership,
                "employment_type": r.employment_type,
                "requires_district_approval": r.requires_district_approval,
                "note": r.note,
            }
            for r in rows
        ]
    }


POLICY_OWNERSHIPS = {"public", "non_profit", "private"}
POLICY_EMPLOYMENT_TYPES = {"official", "contractual", "part_time", "temporary"}


class PolicyIn(BaseModel):
    school_ownership: str
    employment_type: str
    requires_district_approval: bool
    note: str | None = None


@router.post("/employment-policy")
async def upsert_policy(
    body: PolicyIn,
    current: AuthUser = Depends(require_permission("manage_employment_policy")),
    db: AsyncSession = Depends(get_db),
):
    """جدول سیاست استخدام قابل نوشتن است (RBAC spec §5 — «Policy Table، نه
    منطق سخت‌کدشده»): ایجاد/به‌روزرسانی قانون بر اساس (مالکیت × نوع استخدام).
    فقط حوزه ناحیه/استان/کشور (سطح ناحیه و بالاتر)."""
    if body.school_ownership not in POLICY_OWNERSHIPS:
        raise HTTPException(400, "نوع مالکیت نامعتبر است")
    if body.employment_type not in POLICY_EMPLOYMENT_TYPES:
        raise HTTPException(400, "نوع استخدام نامعتبر است")
    grants = await grants_of(db, current.id, "manage_employment_policy")
    if not any(scope_type in BROAD_SCOPES for scope_type, _ in grants):
        raise HTTPException(403, "ویرایش سیاست استخدام فقط در سطح ناحیه، استان یا کشور مجاز است")

    rule = (
        await db.execute(
            select(EmploymentPolicyRule).where(
                EmploymentPolicyRule.school_ownership == body.school_ownership,
                EmploymentPolicyRule.employment_type == body.employment_type,
            )
        )
    ).scalar_one_or_none()
    if rule is None:
        rule = EmploymentPolicyRule(
            school_ownership=body.school_ownership,
            employment_type=body.employment_type,
            requires_district_approval=body.requires_district_approval,
            note=body.note,
        )
        db.add(rule)
    else:
        rule.requires_district_approval = body.requires_district_approval
        if body.note is not None:
            rule.note = body.note
    await db.flush()
    await db.commit()
    return {
        "ok": True,
        "rule": {
            "id": rule.id,
            "school_ownership": rule.school_ownership,
            "employment_type": rule.employment_type,
            "requires_district_approval": rule.requires_district_approval,
            "note": rule.note,
        },
    }


# ------------------------- مجوزها: تفویض/لغو با قاعده طلایی -------------------------


class GrantIn(BaseModel):
    grantee_user_id: int
    role_id: int
    permission_id: int
    scope_type: str
    scope_id: int
    valid_from: date | None = None
    valid_until: date | None = None


@router.post("/permissions/grant")
async def grant(
    body: GrantIn,
    current: AuthUser = Depends(require_permission("manage_permissions")),
    db: AsyncSession = Depends(get_db),
):
    """قاعده طلایی در بک‌اند اعمال می‌شود نه فقط UI (RBAC spec §8):
    ۱) تفویض‌کننده باید manage_permissions در حوزه هدف داشته باشد،
    ۲) و خودِ مجوزِ واگذارشده را در حوزه‌ای که هدف را بپوشاند داشته باشد.
    هر ردی = لاگ ممیزی + HTTP 403 با پیام فارسی."""
    if not await has_permission_in_scope(db, current.id, "manage_permissions", body.scope_type, body.scope_id):
        await log_action(
            db,
            actor_user_id=current.id,
            action="delegation_denied_insufficient_owner_permission",
            entity_type="user",
            entity_id=body.grantee_user_id,
            detail=f"permission=manage_permissions scope={body.scope_type}:{body.scope_id}",
        )
        await db.commit()
        raise HTTPException(403, "شما در این حوزه اختیار تفویض مجوز ندارید")

    result = await grant_permission(
        db,
        grantor_user_id=current.id,
        grantee_user_id=body.grantee_user_id,
        role_id=body.role_id,
        permission_id=body.permission_id,
        scope_type=body.scope_type,
        scope_id=body.scope_id,
        valid_from=body.valid_from,
        valid_until=body.valid_until,
    )
    if not result.get("ok"):
        await db.commit()  # لاگ ممیزی ردّ تفویض باید پایدار بماند
        if result.get("not_found"):
            raise HTTPException(404, detail=result["reason"])
        raise HTTPException(403, detail=result["reason"])
    await db.commit()
    return result


@router.post("/permissions/{assignment_id}/revoke")
async def revoke(
    assignment_id: int,
    current: AuthUser = Depends(require_permission("manage_permissions")),
    db: AsyncSession = Depends(get_db),
):
    result = await revoke_permission(db, actor_user_id=current.id, assignment_id=assignment_id)
    if not result.get("ok"):
        await db.commit()  # لاگ ممیزی ردّ لغو باید پایدار بماند
        if result.get("not_found"):
            raise HTTPException(404, detail="تخصیص مجوز یافت نشد")
        raise HTTPException(403, detail=result["reason"])
    await db.commit()
    return result


@router.get("/permissions/mine")
async def my_permissions(current: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    keys = await effective_permissions(db, current.id)
    scopes = await user_scopes(db, current.id)
    return {"permissions": sorted(keys), "scopes": scopes}


# ------------------------- معاونان (RBAC spec §6) -------------------------


class DeputyIn(BaseModel):
    title_fa: str
    permission_keys: list[str]


class DeputyPatchIn(BaseModel):
    title_fa: str | None = None
    permission_keys: list[str] | None = None
    is_active: bool | None = None


class DeputyAssignIn(BaseModel):
    user_id: int


async def _validate_deputy_keys(db: AsyncSession, keys: list[str]) -> None:
    """هر کلید چک‌لیست باید در جدول Permission موجود باشد."""
    for key in keys:
        found = (await db.execute(select(Permission.id).where(Permission.key == key))).first()
        if found is None:
            raise HTTPException(400, f"مجوز نامعتبر: {key}")


async def _deputy_users(db: AsyncSession, school_id: int) -> list[dict]:
    """کاربران دارای تخصیص فعال role=deputy در این مدرسه."""
    rows = (
        await db.execute(
            select(SchoolAssignment).where(
                SchoolAssignment.school_id == school_id,
                SchoolAssignment.role == "deputy",
                SchoolAssignment.status == "active",
            )
        )
    ).scalars().all()
    out = []
    for assignment in rows:
        employee = await db.get(Employee, assignment.employee_id)
        user = await db.get(User, employee.user_id) if employee else None
        if user is None:
            continue
        out.append(
            {
                "user_id": user.id,
                "full_name": user.full_name,
                "title_fa": assignment.subject,
                "assignment_id": assignment.id,
            }
        )
    return out


def _deputy_row(deputy: Deputy, assigned: list[dict] | None = None) -> dict:
    return {
        "id": deputy.id,
        "school_id": deputy.school_id,
        "title_fa": deputy.title_fa,
        "permission_keys": list(deputy.permission_keys or []),
        "is_active": deputy.is_active,
        "assigned_users": [u for u in (assigned or []) if u.get("title_fa") == deputy.title_fa],
    }


@router.get("/schools/{school_id}/deputies")
async def list_deputies(
    school_id: int,
    current: AuthUser = Depends(require_permission("view_school_analytics", scope_type="school", scope_param="school_id")),
    db: AsyncSession = Depends(get_db),
):
    """فهرست معاونان مدرسه + کاربران متصل (district spec §16 — مدیر ناحیه
    معاونان را می‌بیند؛ چک‌لیست را مدیر مدرسه تعیین می‌کند)."""
    if await db.get(School, school_id) is None:
        raise HTTPException(404, "مدرسه یافت نشد")
    deputies = (
        await db.execute(select(Deputy).where(Deputy.school_id == school_id).order_by(Deputy.id))
    ).scalars().all()
    assigned = await _deputy_users(db, school_id)
    return {"school_id": school_id, "deputies": [_deputy_row(d, assigned) for d in deputies]}


@router.post("/schools/{school_id}/deputies")
async def create_deputy(
    school_id: int,
    body: DeputyIn,
    current: AuthUser = Depends(require_permission("manage_deputies", scope_type="school", scope_param="school_id")),
    db: AsyncSession = Depends(get_db),
):
    """ساخت نقش معاون با چک‌لیست مجوز (رویداد deputy_role_created)."""
    if await db.get(School, school_id) is None:
        raise HTTPException(404, "مدرسه یافت نشد")
    if not body.title_fa.strip():
        raise HTTPException(400, "عنوان معاون الزامی است")
    await _validate_deputy_keys(db, body.permission_keys)
    deputy = Deputy(school_id=school_id, title_fa=body.title_fa.strip(), permission_keys=body.permission_keys, is_active=True)
    db.add(deputy)
    await db.flush()
    await log_action(
        db,
        actor_user_id=current.id,
        action="deputy_role_created",
        entity_type="deputy",
        entity_id=deputy.id,
        detail=f"school={school_id} keys={','.join(body.permission_keys)}",
    )
    await db.commit()
    return {"ok": True, "deputy": _deputy_row(deputy)}


@router.patch("/schools/{school_id}/deputies/{deputy_id}")
async def update_deputy(
    school_id: int,
    deputy_id: int,
    body: DeputyPatchIn,
    current: AuthUser = Depends(require_permission("manage_deputies", scope_type="school", scope_param="school_id")),
    db: AsyncSession = Depends(get_db),
):
    """ویرایش چک‌لیست فقط توسط مدیر مدرسه (RBAC spec §6 — «مدیر مدرسه هر
    زمان می‌تواند این چک‌لیست را تغییر دهد»)."""
    if current.system_role not in ("school_admin", "platform_admin"):
        raise HTTPException(403, "ویرایش چک‌لیست مجوز معاون فقط برای مدیر مدرسه مجاز است")
    deputy = await db.get(Deputy, deputy_id)
    if deputy is None or deputy.school_id != school_id:
        raise HTTPException(404, "معاون یافت نشد")
    if body.permission_keys is not None:
        await _validate_deputy_keys(db, body.permission_keys)
        deputy.permission_keys = body.permission_keys
    if body.title_fa is not None:
        if not body.title_fa.strip():
            raise HTTPException(400, "عنوان معاون نمی‌تواند خالی باشد")
        deputy.title_fa = body.title_fa.strip()
    if body.is_active is not None:
        deputy.is_active = body.is_active
    await db.commit()
    return {"ok": True, "deputy": _deputy_row(deputy)}


@router.delete("/schools/{school_id}/deputies/{deputy_id}")
async def delete_deputy(
    school_id: int,
    deputy_id: int,
    current: AuthUser = Depends(require_permission("manage_deputies", scope_type="school", scope_param="school_id")),
    db: AsyncSession = Depends(get_db),
):
    """حذف (غیرفعال‌سازی) نقش معاون — مجوزهای قبلاً واگذارشده دست‌نخورده
    می‌مانند؛ تاریخچه ممیزی حفظ می‌شود."""
    deputy = await db.get(Deputy, deputy_id)
    if deputy is None or deputy.school_id != school_id:
        raise HTTPException(404, "معاون یافت نشد")
    deputy.is_active = False
    await db.commit()
    return {"ok": True, "deputy": _deputy_row(deputy)}


@router.post("/schools/{school_id}/deputies/{deputy_id}/assign-user")
async def assign_deputy_user(
    school_id: int,
    deputy_id: int,
    body: DeputyAssignIn,
    current: AuthUser = Depends(require_permission("manage_deputies", scope_type="school", scope_param="school_id")),
    db: AsyncSession = Depends(get_db),
):
    """اتصال کاربر به نقش معاون: همه کلیدهای چک‌لیست با حوزه مدرسه و از
    طریق rbac_service واگذار می‌شوند (قاعده طلایی + لاگ ممیزی خودکار)، به
   علاوه لینک SchoolAssignment(role="deputy")."""
    deputy = await db.get(Deputy, deputy_id)
    if deputy is None or deputy.school_id != school_id:
        raise HTTPException(404, "معاون یافت نشد")
    if not deputy.is_active:
        raise HTTPException(400, "این نقش معاون غیرفعال است")
    user = await db.get(User, body.user_id)
    if user is None or not user.is_active:
        raise HTTPException(404, "کاربر یافت نشد")

    keys = list(deputy.permission_keys or [])
    await _validate_deputy_keys(db, keys)

    # پیش‌بررسی قاعده طلایی برای همه کلیدها — پیش از ایجاد هر رکوردی
    for key in keys:
        check = await check_delegation_scope(
            db,
            grantor_user_id=current.id,
            grantee_user_id=user.id,
            permission_key=key,
            scope_type="school",
            scope_id=school_id,
        )
        if not check["ok"]:
            await db.commit()  # لاگ ردّ تفویض پایدار بماند
            raise HTTPException(403, detail=check["reason"])

    role = (await db.execute(select(Role).where(Role.key == "deputy"))).scalar_one_or_none()
    if keys and role is None:
        raise HTTPException(400, "نقش «معاون» در سیستم تعریف نشده است")

    granted: list[str] = []
    for key in keys:
        permission = (await db.execute(select(Permission).where(Permission.key == key))).scalar_one_or_none()
        result = await grant_permission(
            db,
            grantor_user_id=current.id,
            grantee_user_id=user.id,
            role_id=role.id,
            permission_id=permission.id,
            scope_type="school",
            scope_id=school_id,
        )
        if not result.get("ok"):
            await db.commit()
            raise HTTPException(403, detail=result["reason"])
        granted.append(key)

    employee = (
        await db.execute(select(Employee).where(Employee.user_id == user.id))
    ).scalar_one_or_none()
    if employee is None:
        employee = Employee(user_id=user.id)
        db.add(employee)
        await db.flush()

    existing = (
        await db.execute(
            select(SchoolAssignment).where(
                SchoolAssignment.employee_id == employee.id,
                SchoolAssignment.school_id == school_id,
                SchoolAssignment.role == "deputy",
                SchoolAssignment.status == "active",
            )
        )
    ).scalar_one_or_none()
    assignment_id = existing.id if existing is not None else None
    if existing is None:
        assignment = SchoolAssignment(
            employee_id=employee.id,
            school_id=school_id,
            role="deputy",
            subject=deputy.title_fa,
            start_date=date.today(),
            status="active",
        )
        db.add(assignment)
        await db.flush()
        assignment_id = assignment.id
    await db.commit()
    return {"ok": True, "granted": granted, "assignment_id": assignment_id}


# ------------------------- انتقال کارکنان (RBAC spec §10) -------------------------


class TransferIn(BaseModel):
    new_school_id: int
    subject: str | None = None
    effective_date: date | None = None


@router.post("/school-assignments/{assignment_id}/transfer")
async def transfer_assignment(
    assignment_id: int,
    body: TransferIn,
    current: AuthUser = Depends(require_permission("manage_employment")),
    db: AsyncSession = Depends(get_db),
):
    """§10 انتقال معلم بین مدرسه‌ها: تخصیص قدیمی با تاریخ مؤثر بسته می‌شود،
    تخصیص جدید برای همان فرد ساخته می‌شود؛ اسناد تاریخی (AttemptAnswer)
    هرگز تغییر نمی‌کنند. گارد: حوزه ناحیه/استان/کشور که هر دو مدرسه را
    بپوشاند."""
    assignment = await db.get(SchoolAssignment, assignment_id)
    if assignment is None:
        raise HTTPException(404, "تخصیص یافت نشد")
    if assignment.status != "active":
        raise HTTPException(400, "فقط تخصیص فعال قابل انتقال است")
    new_school = await db.get(School, body.new_school_id)
    if new_school is None:
        raise HTTPException(404, "مدرسه مقصد یافت نشد")
    if new_school.id == assignment.school_id:
        raise HTTPException(400, "مدرسه مقصد با مدرسه فعلی یکسان است")

    if current.system_role != "platform_admin":
        from_school = await covering_grants(db, current.id, "manage_employment", "school", assignment.school_id)
        to_school = await covering_grants(db, current.id, "manage_employment", "school", new_school.id)
        covers_both = [
            (scope_type, scope_id)
            for (scope_type, scope_id) in from_school
            if scope_type in BROAD_SCOPES and (scope_type, scope_id) in to_school
        ]
        if not covers_both:
            raise HTTPException(403, "انتقال کارکنان نیازمند دسترسی ناحیه/استان است که هر دو مدرسه را بپوشاند")

    effective = body.effective_date or date.today()
    old_school_id = assignment.school_id
    assignment.end_date = effective
    assignment.status = "ended"

    new_assignment = SchoolAssignment(
        employee_id=assignment.employee_id,
        school_id=new_school.id,
        role=assignment.role,
        subject=body.subject if body.subject is not None else assignment.subject,
        start_date=effective,
        status="active",
    )
    db.add(new_assignment)
    await db.flush()
    await log_action(
        db,
        actor_user_id=current.id,
        action="school_assignment_transferred",
        entity_type="school_assignment",
        entity_id=assignment.id,
        detail=(
            f"from={old_school_id} to={new_school.id} effective={effective} "
            f"new_assignment={new_assignment.id}"
        ),
    )
    await db.commit()
    return {
        "ok": True,
        "old_assignment_id": assignment.id,
        "new_assignment_id": new_assignment.id,
        "status": assignment.status,
        "effective_date": effective,
    }
