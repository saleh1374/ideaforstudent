"""Admin APIs (school admin spec + district spec + RBAC spec §16-18):
aggregated overviews, employment request inbox with scope filtering,
permission grant/revoke with the golden rule (403 on denial), deputies
(معاونان §6), teacher transfer (§10) + فهرست معلمان، ثبت‌نام/پذیرش
دانش‌آموز و افزودن مستقیم دانش‌آموز (Features A/B)."""
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthUser, get_current_user, require_permission
from app.core.db import get_db
from app.core.passwords import hash_password
from app.models.employment import EmploymentPolicyRule, EmploymentRequest
from app.models.org import (
    AdmissionRequest,
    ClassRoom,
    ClassTeacherAssignment,
    Employee,
    School,
    SchoolAssignment,
    StudentProfile,
    User,
)
from app.models.rbac import Deputy, Permission, Role
from app.models.school_copilot import SchoolSuggestion
from app.models.slm import StudentTopicState
from app.services import admission as admission_svc
from app.services import school as school_svc
from app.services import school_copilot as copilot_svc
from app.services import school_ops as ops_svc
from app.services import school_views
from app.services.employment import decide_request, is_principal_of, submit_teacher_request
from app.services.rbac_service import (
    check_delegation_scope,
    covering_grants,
    effective_permissions,
    grant_permission,
    grants_of,
    has_permission,
    has_permission_in_scope,
    log_action,
    revoke_permission,
    user_scopes,
    visible_school_ids,
)

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


@router.get("/school/{school_id}/teachers-compare")
async def teachers_compare_endpoint(
    school_id: int,
    subject: str = "math",
    current: AuthUser = Depends(require_permission("view_school_analytics", scope_type="school", scope_param="school_id")),
    db: AsyncSession = Depends(get_db),
):
    """§8 مقایسه معلم با معلم — با احتیاط: تسط/رشد/ماندگاری هر کلاس + عوامل
    زمینه‌ای؛ بدون امتیاز کلی و با سرکوب حداقل جمعیت."""
    if await db.get(School, school_id) is None:
        raise HTTPException(404, "مدرسه یافت نشد")
    return await school_views.teacher_comparison(db, school_id, subject)


@router.get("/school/{school_id}/students")
async def list_school_students_endpoint(
    school_id: int,
    current: AuthUser = Depends(require_permission("view_students", scope_type="school", scope_param="school_id")),
    db: AsyncSession = Depends(get_db),
):
    """فهرست دانش‌آموزان مدرسه برای انتخابگر نمای فردی (§13)."""
    if await db.get(School, school_id) is None:
        raise HTTPException(404, "مدرسه یافت نشد")
    return await school_views.list_students(db, school_id)


@router.get("/school/{school_id}/students/{user_id}")
async def school_student_detail_endpoint(
    school_id: int,
    user_id: int,
    current: AuthUser = Depends(require_permission("view_students", scope_type="school", scope_param="school_id")),
    db: AsyncSession = Depends(get_db),
):
    """§13 نمای فردی دانش‌آموز برای مدیر: تسط/ماندگاری/رتبه کلاسی/روند +
    خطاها/مباحث بحرانی/تکمیل تمرین + مشکل اصلی + چرخه مداخله + آزمون‌های اخیر."""
    if await db.get(School, school_id) is None:
        raise HTTPException(404, "مدرسه یافت نشد")
    try:
        return await school_views.student_detail(db, school_id, user_id)
    except LookupError:
        raise HTTPException(404, "این دانش‌آموز در این مدرسه ثبت نشده است")


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


@router.get("/teachers-directory")
async def teachers_directory(
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """فهرست معلمان برای «انتخاب معلم از فهرست» در درخواست استخدام (Feature A
    — جایگزین فرم هاردکد): همه کاربران با نقش معلم به همراه تخصیص‌های فعالشان.
    گارد: داشتن view_students یا manage_employment (در هر حوزه‌ای). دید
    حوزه‌مند: متقاضی می‌تواند از روی active_assignments ببیند معلم کجا شاغل
    است و available فقط برای معلمان بدون هیچ تخصیص فعالی True است."""
    if not (
        await has_permission(db, current.id, "view_students")
        or await has_permission(db, current.id, "manage_employment")
    ):
        raise HTTPException(403, "دسترسی لازم: view_students یا manage_employment")

    teachers = (
        await db.execute(select(User).where(User.system_role == "teacher").order_by(User.id))
    ).scalars().all()
    if not teachers:
        return {"total": 0, "teachers": []}

    teacher_ids = [t.id for t in teachers]
    employees = (
        await db.execute(select(Employee).where(Employee.user_id.in_(teacher_ids)))
    ).scalars().all()

    schools = {s.id: s.name for s in (await db.execute(select(School))).scalars().all()}

    assignments_by_user: dict[int, list[SchoolAssignment]] = {}
    if employees:
        employee_user = {e.id: e.user_id for e in employees}
        rows = (
            await db.execute(
                select(SchoolAssignment)
                .where(
                    SchoolAssignment.employee_id.in_([e.id for e in employees]),
                    SchoolAssignment.status == "active",
                )
                .order_by(SchoolAssignment.id)
            )
        ).scalars().all()
        for assignment in rows:
            user_id = employee_user.get(assignment.employee_id)
            if user_id is not None:
                assignments_by_user.setdefault(user_id, []).append(assignment)

    out = []
    for t in teachers:
        assigns = assignments_by_user.get(t.id, [])
        out.append(
            {
                "user_id": t.id,
                "full_name": t.full_name,
                "username": t.username,
                "subjects": sorted({a.subject for a in assigns if a.subject}),
                "active_assignments": [
                    {
                        "school_id": a.school_id,
                        "school_name": schools.get(a.school_id),
                        "role": a.role,
                        "subject": a.subject,
                    }
                    for a in assigns
                ],
                "available": not assigns,
            }
        )
    return {"total": len(out), "teachers": out}


@router.get("/employment-requests")
async def list_employment_requests(
    current: AuthUser = Depends(require_permission("manage_employment")),
    db: AsyncSession = Depends(get_db),
):
    """فقط درخواست‌های مدارسِ در حوزه دید تماس‌گیرنده (مدیر ناحیه ناحیه خودش
    را می‌بیند — district spec §33 دسترسی مبتنی بر محدوده). سطرها برای UI
    نام مدرسه و شناسه معلم (teacher_user_id) هم دارند."""
    rows = (
        await db.execute(select(EmploymentRequest).order_by(EmploymentRequest.created_at.desc()))
    ).scalars().all()
    visible = await visible_school_ids(db, current.id, "manage_employment")
    if visible is not None:
        rows = [r for r in rows if r.school_id in visible]
    schools = {s.id: s.name for s in (await db.execute(select(School))).scalars().all()}
    return {
        "requests": [
            {
                "id": r.id,
                "school_id": r.school_id,
                "school_name": schools.get(r.school_id),
                "full_name": r.full_name,
                "teacher_user_id": r.employee_user_id,
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
    teacher_user_id: int | None = None  # مسیر جدید: انتخاب از فهرست معلمان
    employee_user_id: int | None = None  # سازگاری عقب‌رو با payloadهای قدیمی
    full_name: str | None = None  # اختیاری — همیشه از پروفایل کاربر پر می‌شود
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
    ناحیه/استان روی آن مدرسه (RBAC spec §5 + district spec §14).
    انتخاب معلم با teacher_user_id (Feature A): کاربر باید وجود داشته باشد،
    نقشش teacher باشد و در این مدرسه تخصیص فعال نداشته باشد (409)."""
    school = await db.get(School, body.school_id)
    if school is None:
        raise HTTPException(404, "مدرسه یافت نشد")
    if not await is_principal_of(db, current.id, body.school_id):
        grants = await covering_grants(db, current.id, "manage_employment", "school", body.school_id)
        if not any(scope_type in BROAD_SCOPES for scope_type, _ in grants):
            raise HTTPException(
                403, "ثبت درخواست استخدام فقط برای مدیر همان مدرسه یا مسئول ناحیه/استان مجاز است"
            )

    # شناسه معلم: teacher_user_id (جدید) یا employee_user_id (سازگاری عقب‌رو)
    teacher_user_id = (
        body.teacher_user_id if body.teacher_user_id is not None else body.employee_user_id
    )
    if teacher_user_id is None:
        raise HTTPException(400, "شناسه معلم (teacher_user_id) الزامی است")
    teacher = await db.get(User, teacher_user_id)
    if teacher is None:
        raise HTTPException(404, "کاربر یافت نشد")
    # اعتبارسنجی نقش فقط در مسیر جدید؛ مسیر قدیمی employee_user_id صرفاً
    # شناسه کاربر را می‌پذیرد (سازگاری با payloadهای موجود)
    if body.teacher_user_id is not None and teacher.system_role != "teacher":
        raise HTTPException(400, "فقط کاربران با نقش معلم قابل انتخاب هستند")

    # این معلم هم‌اکنون در این مدرسه شاغل است؟
    employee = (
        await db.execute(select(Employee).where(Employee.user_id == teacher.id))
    ).scalar_one_or_none()
    if employee is not None:
        active = (
            await db.execute(
                select(SchoolAssignment.id)
                .where(
                    SchoolAssignment.employee_id == employee.id,
                    SchoolAssignment.school_id == body.school_id,
                    SchoolAssignment.status == "active",
                )
                .limit(1)
            )
        ).first()
        if active is not None:
            raise HTTPException(409, "این معلم هم‌اکنون در این مدرسه شاغل است")

    result = await submit_teacher_request(
        db,
        school_id=body.school_id,
        requested_by=current.id,
        employee_user_id=teacher.id,
        full_name=teacher.full_name,  # نام از پروفایل کاربر — مغایرت کلاینت نادیده گرفته می‌شود
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


# ------------------------- پذیرش ثبت‌نام دانش‌آموز (Feature B) -------------------------

ADMISSION_STATUSES = ("pending", "approved", "rejected")


@router.get("/admission-requests")
async def list_admission_requests(
    status: str | None = None,
    current: AuthUser = Depends(require_permission("manage_admissions")),
    db: AsyncSession = Depends(get_db),
):
    """درخواست‌های ثبت‌نام در حوزه دید تماس‌گیرنده: مدرسه‌دار فقط مدرسه
    خودش را می‌بیند؛ ناحیه/استان/کشور (حوزه وسیع) درخواست‌های بدون مدرسه
    را هم می‌بینند تا هنگام تأیید مدرسه‌شان را تعیین کنند."""
    if status is not None and status not in ADMISSION_STATUSES:
        raise HTTPException(400, "وضعیت نامعتبر است (pending | approved | rejected)")
    rows = (
        await db.execute(select(AdmissionRequest).order_by(AdmissionRequest.created_at.desc(), AdmissionRequest.id.desc()))
    ).scalars().all()

    visible = await visible_school_ids(db, current.id, "manage_admissions")
    grants = await grants_of(db, current.id, "manage_admissions")
    broad = any(scope_type in BROAD_SCOPES for scope_type, _ in grants)
    schools = {s.id: s.name for s in (await db.execute(select(School))).scalars().all()}

    out = []
    for r in rows:
        if visible is not None:
            if r.school_id is None:
                if not broad:
                    continue  # بدون مدرسه → فقط سطح ناحیه و بالاتر
            elif r.school_id not in visible:
                continue
        if status is not None and r.status != status:
            continue
        out.append(
            {
                "id": r.id,
                "full_name": r.full_name,
                "username": r.username,
                "grade": r.grade,
                "phone": r.phone,
                "school_id": r.school_id,
                "school_name": schools.get(r.school_id) if r.school_id is not None else None,
                "status": r.status,
                "created_at": r.created_at,
            }
        )
    return {"total": len(out), "requests": out}


class AdmissionDecisionIn(BaseModel):
    approve: bool
    class_id: int | None = None  # اگر ندهید: نخستین کلاس مدرسه انتخاب می‌شود
    school_id: int | None = None  # فقط برای درخواست‌های بدون مدرسه انتخابی


@router.post("/admission-requests/{request_id}/decide")
async def decide_admission_request(
    request_id: int,
    body: AdmissionDecisionIn,
    current: AuthUser = Depends(require_permission("manage_admissions")),
    db: AsyncSession = Depends(get_db),
):
    """تصمیم روی درخواست ثبت‌نام: تأیید = ساخت فوری کاربر (is_active) +
    پروفایل دانش‌آموز؛ رد = فقط تغییر وضعیت. گارد حوزه روی مدرسه خودِ
    درخواست است (مدرسه خارج از حوزه → 403)."""
    req = await db.get(AdmissionRequest, request_id)
    if req is None:
        raise HTTPException(404, "درخواست ثبت‌نام یافت نشد")

    # گارد حوزه: مدرسه درخواست باید در حوزه manage_admissions تماس‌گیرنده باشد
    if req.school_id is not None:
        if not await has_permission_in_scope(db, current.id, "manage_admissions", "school", req.school_id):
            raise HTTPException(403, "دسترسی لازم manage_admissions در حوزه این مدرسه")
    else:
        grants = await grants_of(db, current.id, "manage_admissions")
        if not any(scope_type in BROAD_SCOPES for scope_type, _ in grants):
            raise HTTPException(403, "تعیین مدرسه برای درخواست بدون مدرسه فقط در سطح ناحیه و بالاتر مجاز است")

    if req.status != "pending":
        raise HTTPException(409, "این درخواست قبلاً بررسی شده است")

    if not body.approve:
        req.status = "rejected"
        req.decided_by = current.id
        req.decided_at = datetime.now(timezone.utc)
        await log_action(
            db,
            actor_user_id=current.id,
            action="admission_rejected",
            entity_type="admission_request",
            entity_id=req.id,
            detail=f"username={req.username} school={req.school_id}",
        )
        await db.commit()
        return {"ok": True, "status": "rejected", "request_id": req.id}

    # ---- تأیید: مدرسه و کلاس را روشن کن ----
    school_id = req.school_id
    if school_id is None:
        if body.school_id is not None:
            school_id = body.school_id
        elif body.class_id is not None:
            class_row = await db.get(ClassRoom, body.class_id)
            if class_row is None:
                raise HTTPException(404, "کلاس یافت نشد")
            school_id = class_row.school_id
        else:
            raise HTTPException(400, "برای این درخواست باید مدرسه‌ای تعیین شود")
    if await db.get(School, school_id) is None:
        raise HTTPException(404, "مدرسه یافت نشد")

    if body.class_id is not None:
        class_room = await db.get(ClassRoom, body.class_id)
        if class_room is None:
            raise HTTPException(404, "کلاس یافت نشد")
        if class_room.school_id != school_id:
            raise HTTPException(400, "کلاس انتخاب‌شده به این مدرسه تعلق ندارد")
        class_id = class_room.id
    else:
        class_id = await admission_svc.first_class_of_school(db, school_id)

    # نام کاربری باید هنوز در جدول کاربران آزاد باشد (خودِ درخواست pending است)
    if (await db.execute(select(User.id).where(User.username == req.username))).first() is not None:
        raise HTTPException(409, admission_svc.DUP_USERNAME)

    user = User(
        username=req.username,
        password_hash=req.password_hash,
        full_name=req.full_name,
        phone=req.phone,
        system_role="student",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    profile = StudentProfile(
        user_id=user.id,
        grade=req.grade,
        school_id=school_id,
        class_id=class_id,
        status="active",
    )
    db.add(profile)

    req.school_id = school_id
    req.class_id = class_id
    req.status = "approved"
    req.decided_by = current.id
    req.decided_at = datetime.now(timezone.utc)
    await log_action(
        db,
        actor_user_id=current.id,
        action="admission_approved",
        entity_type="admission_request",
        entity_id=req.id,
        detail=f"username={req.username} school={school_id} class={class_id}",
    )
    await db.commit()
    return {
        "ok": True,
        "status": "approved",
        "request_id": req.id,
        "user_id": user.id,
        "school_id": school_id,
        "class_id": class_id,
    }


# ------------------------- کلاس‌ها و افزودن مستقیم دانش‌آموز (Feature B) -------------------------


@router.get("/school/{school_id}/classes")
async def school_classes(
    school_id: int,
    current: AuthUser = Depends(require_permission("view_students", scope_type="school", scope_param="school_id")),
    db: AsyncSession = Depends(get_db),
):
    """کلاس‌های مدرسه برای انتخابگر کلاس (تأیید ثبت‌نام / افزودن مستقیم) —
    همان گارد حوزه مدرسه بقیه endpointهای /admin/school/*."""
    if await db.get(School, school_id) is None:
        raise HTTPException(404, "مدرسه یافت نشد")
    classes = (
        await db.execute(select(ClassRoom).where(ClassRoom.school_id == school_id).order_by(ClassRoom.id))
    ).scalars().all()
    counts: dict[int, int] = {}
    if classes:
        rows = (
            await db.execute(
                select(StudentProfile.class_id, func.count())
                .where(StudentProfile.class_id.in_([c.id for c in classes]))
                .group_by(StudentProfile.class_id)
            )
        ).all()
        counts = {class_id: total for class_id, total in rows}
    return [
        {
            "id": c.id,
            "name": c.name,
            "grade": c.grade,
            "capacity": c.capacity,
            "students_count": counts.get(c.id, 0),
        }
        for c in classes
    ]


class DirectStudentIn(BaseModel):
    username: str
    password: str
    full_name: str
    grade: str
    class_id: int


@router.post("/students")
async def create_student_direct(
    body: DirectStudentIn,
    current: AuthUser = Depends(require_permission("manage_admissions")),
    db: AsyncSession = Depends(get_db),
):
    """«افزودن مستقیم دانش‌آموز» توسط مدیر مدرسه (بدون ثبت‌نام عمومی):
    کاربر + پروفایل در همان لحظه ساخته می‌شوند؛ حوزه manage_admissions باید
    همان کلاس را بپوشاند (کلاس مدرسه دیگر → 403)."""
    username = body.username.strip()
    if not admission_svc.username_format_ok(username):
        raise HTTPException(400, "نام کاربری نامعتبر است")
    if len(body.password) < 6:
        raise HTTPException(400, "رمز عبور باید حداقل ۶ نویسه باشد")
    if not body.full_name.strip():
        raise HTTPException(400, "نام کامل الزامی است")
    if not admission_svc.grade_ok(body.grade):
        raise HTTPException(400, "پایه تحصیلی نامعتبر است")

    class_room = await db.get(ClassRoom, body.class_id)
    if class_room is None:
        raise HTTPException(404, "کلاس یافت نشد")
    if not await has_permission_in_scope(db, current.id, "manage_admissions", "class", class_room.id):
        raise HTTPException(403, "دسترسی لازم manage_admissions در حوزه این کلاس")

    if await admission_svc.username_taken(db, username):
        raise HTTPException(409, admission_svc.DUP_USERNAME)

    user = User(
        username=username,
        password_hash=hash_password(body.password),
        full_name=body.full_name.strip(),
        system_role="student",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    profile = StudentProfile(
        user_id=user.id,
        grade=body.grade,
        school_id=class_room.school_id,
        class_id=class_room.id,
        status="active",
    )
    db.add(profile)
    await log_action(
        db,
        actor_user_id=current.id,
        action="student_created",
        entity_type="user",
        entity_id=user.id,
        detail=f"class={class_room.id} school={class_room.school_id} grade={body.grade}",
    )
    await db.commit()
    return {
        "ok": True,
        "user_id": user.id,
        "profile_id": profile.id,
        "school_id": class_room.school_id,
        "class_id": class_room.id,
    }


# ------------------------- دستیار هوشمند مدیر مدرسه (§16 و §18) -------------------------


class CopilotChatIn(BaseModel):
    message: str
    conversation_id: int | None = None


@router.post("/school/{school_id}/copilot/chat")
async def school_copilot_chat(
    school_id: int,
    body: CopilotChatIn,
    current: AuthUser = Depends(require_permission("view_school_analytics", scope_type="school", scope_param="school_id")),
    db: AsyncSession = Depends(get_db),
):
    """§16 پرسش/پاسخ تحلیلی مدیر روی داده تجمیعی همین مدرسه: تشخیص نیت →
    بازیابی از تجمیع‌های واقعی → پاسخ با «منابع». بدون کش سراسری (پاسخ
    حاوی داده اختصاصی مدرسه است — حریم خصوصی §20). هر پرسش با رویداد
    school_copilot_query در لاگ ممیزی ثبت می‌شود."""
    message = body.message.strip()
    if not message:
        raise HTTPException(400, "متن پرسش نمی‌تواند خالی باشد")
    if await db.get(School, school_id) is None:
        raise HTTPException(404, "مدرسه یافت نشد")

    result = await copilot_svc.chat(
        db,
        school_id=school_id,
        actor_user_id=current.id,
        message=message,
        conversation_id=body.conversation_id,
    )
    await log_action(
        db,
        actor_user_id=current.id,
        action="school_copilot_query",
        entity_type="school",
        entity_id=school_id,
        detail=f"intent={result['intent']} conv={result['conversation_id']}",
    )
    await db.commit()
    return result


@router.get("/school/{school_id}/copilot/conversations")
async def school_copilot_conversations(
    school_id: int,
    current: AuthUser = Depends(require_permission("view_school_analytics", scope_type="school", scope_param="school_id")),
    db: AsyncSession = Depends(get_db),
):
    """فهرست گفت‌وگوهای قبلی مدیر با کوپایلت (فقط همین مدرسه)."""
    if await db.get(School, school_id) is None:
        raise HTTPException(404, "مدرسه یافت نشد")
    return {"conversations": await copilot_svc.list_conversations(db, school_id)}


@router.get("/school/{school_id}/copilot/conversations/{conversation_id}")
async def school_copilot_conversation_detail(
    school_id: int,
    conversation_id: int,
    current: AuthUser = Depends(require_permission("view_school_analytics", scope_type="school", scope_param="school_id")),
    db: AsyncSession = Depends(get_db),
):
    """پیام‌های یک گفت‌وگو — گفت‌وگوی مدرسه دیگر یا ناشناس → 404."""
    if await db.get(School, school_id) is None:
        raise HTTPException(404, "مدرسه یافت نشد")
    data = await copilot_svc.conversation_messages(db, school_id, conversation_id)
    if data is None:
        raise HTTPException(404, "گفت‌وگو یافت نشد")
    return data


def _suggestion_row(s: SchoolSuggestion) -> dict:
    return {
        "id": s.id,
        "school_id": s.school_id,
        "class_id": s.class_id,
        "subject": s.subject,
        "title_fa": s.title_fa,
        "evidence_fa": s.evidence_fa,
        "actions_fa": list(s.actions_fa or []),
        "status": s.status,
        "final_actions_fa": list(s.final_actions_fa) if s.final_actions_fa else None,
        "decided_by": s.decided_by,
        "decided_at": s.decided_at,
        "decision_note": s.decision_note,
        "created_at": s.created_at,
    }


@router.get("/school/{school_id}/suggestions")
async def list_school_suggestions(
    school_id: int,
    status: str | None = None,
    current: AuthUser = Depends(require_permission("view_school_analytics", scope_type="school", scope_param="school_id")),
    db: AsyncSession = Depends(get_db),
):
    """§18 پیشنهادهای اقدام مدرسه — «ساخته‌شده توسط سیستم، اجراشده فقط با
    تصمیم مدیر». فیلتر وضعیت اختیاری (proposed|approved|edited|rejected)."""
    if status is not None and status not in ("proposed", "approved", "edited", "rejected"):
        raise HTTPException(400, "وضعیت نامعتبر است")
    if await db.get(School, school_id) is None:
        raise HTTPException(404, "مدرسه یافت نشد")
    q = select(SchoolSuggestion).where(SchoolSuggestion.school_id == school_id)
    if status is not None:
        q = q.where(SchoolSuggestion.status == status)
    rows = (await db.execute(q.order_by(SchoolSuggestion.id.desc()))).scalars().all()
    return {"suggestions": [_suggestion_row(s) for s in rows]}


@router.post("/school/{school_id}/suggestions/generate")
async def generate_school_suggestions(
    school_id: int,
    current: AuthUser = Depends(require_permission("view_school_analytics", scope_type="school", scope_param="school_id")),
    db: AsyncSession = Depends(get_db),
):
    """ساخت پیشنهاد اقدام از پرچم‌های §5 + کلاس‌های دارای افت — idempotent:
    تا وقتی پیشنهاد بازِ همان عنوان هست، چیزی دوباره ساخته نمی‌شود."""
    if await db.get(School, school_id) is None:
        raise HTTPException(404, "مدرسه یافت نشد")
    created = await copilot_svc.generate_suggestions(db, school_id)
    await db.commit()
    return {"ok": True, "created": len(created), "suggestions": [_suggestion_row(s) for s in created]}


class SuggestionDecisionIn(BaseModel):
    action: str  # approve | edit | reject
    edited_actions: list[str] | None = None
    note: str | None = None


@router.post("/school/{school_id}/suggestions/{suggestion_id}/decide")
async def decide_school_suggestion(
    school_id: int,
    suggestion_id: int,
    body: SuggestionDecisionIn,
    current: AuthUser = Depends(require_permission("view_school_analytics", scope_type="school", scope_param="school_id")),
    db: AsyncSession = Depends(get_db),
):
    """§18 اختیار کامل مدیر: تأیید، ویرایش یا رد پیشنهاد — با رویداد
    ممیزی school_suggestion_approved/edited/rejected. خارج از مدرسه → 404؛
    تصمیم تکراری → 409؛ عملیات نامعتبر → 400."""
    if body.action not in ("approve", "edit", "reject"):
        raise HTTPException(400, "عملیات نامعتبر است (approve|edit|reject)")
    if await db.get(School, school_id) is None:
        raise HTTPException(404, "مدرسه یافت نشد")
    try:
        sugg = await copilot_svc.decide_suggestion(
            db,
            school_id=school_id,
            suggestion_id=suggestion_id,
            actor_user_id=current.id,
            action=body.action,
            edited_actions=body.edited_actions,
            note=body.note,
        )
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(409, str(exc))
    if sugg is None:
        raise HTTPException(404, "پیشنهاد یافت نشد")

    await log_action(
        db,
        actor_user_id=current.id,
        action={
            "approve": "school_suggestion_approved",
            "edit": "school_suggestion_edited",
            "reject": "school_suggestion_rejected",
        }[body.action],
        entity_type="school_suggestion",
        entity_id=sugg.id,
        detail=f"school={school_id} note={body.note or ''}",
    )
    await db.commit()
    return {"ok": True, "suggestion": _suggestion_row(sugg)}


# ------------------------- پنل کامل مدیر مدرسه: شیفت، برنامه، کلاس‌ها -------------------------


class ShiftRowIn(BaseModel):
    name: str
    start_time: str
    end_time: str


class ShiftsIn(BaseModel):
    shifts: list[ShiftRowIn]


@router.get("/school/{school_id}/shifts")
async def get_school_shifts(
    school_id: int,
    current: AuthUser = Depends(require_permission("view_school_analytics", scope_type="school", scope_param="school_id")),
    db: AsyncSession = Depends(get_db),
):
    """شیفت‌های مدرسه (تک‌شیفت/دوشیفت با ساعت متغیر — تأیید مدیر مدرسه)."""
    return {"school_id": school_id, "shifts": await ops_svc.list_shifts(db, school_id)}


@router.put("/school/{school_id}/shifts")
async def put_school_shifts(
    school_id: int,
    body: ShiftsIn,
    current: AuthUser = Depends(require_permission("manage_school_ops", scope_type="school", scope_param="school_id")),
    db: AsyncSession = Depends(get_db),
):
    """جایگزینی کامل شیفت‌ها — ۱ تا ۳ شیفت، بدون تداخل ساعتی؛ اگر برنامه
    کلاسی خارج از شیفت جدید شود 400 برمی‌گرداند (اول برنامه اصلاح شود)."""
    result = await ops_svc.set_shifts(
        db, school_id, [s.model_dump() for s in body.shifts], actor_user_id=current.id
    )
    await db.commit()
    return {"ok": True, **result}


@router.get("/school/{school_id}/schedule")
async def get_school_schedule(
    school_id: int,
    current: AuthUser = Depends(require_permission("view_school_analytics", scope_type="school", scope_param="school_id")),
    db: AsyncSession = Depends(get_db),
):
    """برنامه هفتگی همه کلاس‌های مدرسه + شیفت‌ها — نمای یکپارچه مدیر."""
    return await ops_svc.get_school_schedule(db, school_id)


@router.get("/classes/{class_id}/schedule")
async def get_class_schedule(
    class_id: int,
    current: AuthUser = Depends(require_permission("view_school_analytics", scope_type="class", scope_param="class_id")),
    db: AsyncSession = Depends(get_db),
):
    """برنامه هفتگی یک کلاس."""
    return await ops_svc.get_class_schedule(db, class_id)


@router.put("/classes/{class_id}/schedule")
async def put_class_schedule(
    class_id: int,
    body: dict,
    current: AuthUser = Depends(require_permission("manage_school_ops", scope_type="class", scope_param="class_id")),
    db: AsyncSession = Depends(get_db),
):
    """جایگزینی کامل برنامه هفتگی کلاس. اعتبارسنجی: روز ۰ تا ۶، ساعت معتبر،
    انطباق با شیفت مدرسه، عدم تداخل داخل کلاس، عدم تداخل معلم بین کلاس‌ها،
    عضویت معلم در مدرسه. رویداد ممیزی class_schedule_updated."""
    cls = await db.get(ClassRoom, class_id)
    if cls is None:
        raise HTTPException(404, "کلاس یافت نشد")
    entries = body.get("entries") if isinstance(body, dict) else None
    if not isinstance(entries, list):
        raise HTTPException(400, "ساختار درخواست نامعتبر است (entries)")
    result = await ops_svc.replace_class_schedule(
        db, cls.school_id, class_id, entries, actor_user_id=current.id
    )
    await db.commit()
    return {"ok": True, **result}


@router.get("/school/{school_id}/roster")
async def get_school_roster(
    school_id: int,
    current: AuthUser = Depends(require_permission("view_students", scope_type="school", scope_param="school_id")),
    db: AsyncSession = Depends(get_db),
):
    """همه دانش‌آموزان مدرسه با جایگاه کلاسی (کلاس‌ها + بدون کلاس)."""
    return await ops_svc.roster(db, school_id)


@router.post("/school/{school_id}/classes")
async def create_school_class(
    school_id: int,
    body: dict,
    current: AuthUser = Depends(require_permission("manage_school_ops", scope_type="school", scope_param="school_id")),
    db: AsyncSession = Depends(get_db),
):
    """افزودن کلاس جدید به مدرسه."""
    result = await ops_svc.create_class(
        db,
        school_id,
        name=body.get("name", ""),
        grade=body.get("grade", ""),
        track=body.get("track"),
        capacity=int(body.get("capacity") or 30),
        actor_user_id=current.id,
    )
    await db.commit()
    return {"ok": True, "class": result}


@router.patch("/classes/{class_id}")
async def patch_school_class(
    class_id: int,
    body: dict,
    current: AuthUser = Depends(require_permission("manage_school_ops", scope_type="class", scope_param="class_id")),
    db: AsyncSession = Depends(get_db),
):
    """ویرایش نام/ظرفیت کلاس (ظرفیت کمتر از ثبت‌شده → 409)."""
    result = await ops_svc.update_class(
        db,
        class_id,
        name=body.get("name"),
        capacity=body.get("capacity"),
        actor_user_id=current.id,
    )
    await db.commit()
    return {"ok": True, "class": result}


class TeacherAssignIn(BaseModel):
    teacher_user_id: int
    subject: str


@router.get("/classes/{class_id}/teachers")
async def list_class_teachers(
    class_id: int,
    current: AuthUser = Depends(require_permission("view_students", scope_type="class", scope_param="class_id")),
    db: AsyncSession = Depends(get_db),
):
    """تخصیص‌های فعال معلم به این کلاس (برای نمایش و خاتمه تخصیص)."""
    rows = (
        await db.execute(
            select(ClassTeacherAssignment, User.full_name)
            .join(User, ClassTeacherAssignment.teacher_user_id == User.id)
            .where(
                ClassTeacherAssignment.class_id == class_id,
                ClassTeacherAssignment.status == "active",
            )
            .order_by(ClassTeacherAssignment.id)
        )
    ).all()
    return {
        "teachers": [
            {
                "assignment_id": a.id,
                "teacher_user_id": a.teacher_user_id,
                "full_name": name,
                "subject": a.subject,
                "start_date": a.start_date.isoformat() if a.start_date else None,
            }
            for a, name in rows
        ]
    }


@router.post("/classes/{class_id}/teachers")
async def assign_class_teacher(
    class_id: int,
    body: TeacherAssignIn,
    current: AuthUser = Depends(require_permission("manage_school_ops", scope_type="class", scope_param="class_id")),
    db: AsyncSession = Depends(get_db),
):
    """تخصیص معلم به کلاس (عضو معلم در مدرسه الزامی)."""
    result = await ops_svc.assign_teacher(
        db, class_id, body.teacher_user_id, body.subject, actor_user_id=current.id
    )
    await db.commit()
    return {"ok": True, "assignment": result}


@router.delete("/classes/{class_id}/teachers/{assignment_id}")
async def unassign_class_teacher(
    class_id: int,
    assignment_id: int,
    current: AuthUser = Depends(require_permission("manage_school_ops", scope_type="class", scope_param="class_id")),
    db: AsyncSession = Depends(get_db),
):
    """خاتمه تخصیص معلم — تا وقتی در برنامه هفتگی کلاس جلسه دارد 409."""
    result = await ops_svc.unassign_teacher(db, class_id, assignment_id, actor_user_id=current.id)
    await db.commit()
    return result


class StudentMoveIn(BaseModel):
    class_id: int | None = None


@router.patch("/school/{school_id}/students/{user_id}")
async def move_school_student(
    school_id: int,
    user_id: int,
    body: StudentMoveIn,
    current: AuthUser = Depends(require_permission("manage_admissions", scope_type="school", scope_param="school_id")),
    db: AsyncSession = Depends(get_db),
):
    """جابه‌جایی دانش‌آموز بین کلاس‌ها (یا بدون کلاس) — داده واحدی که
    پنل دانش‌آموز/معلم فوراً از همان می‌خوانند. ظرفیت تکمیل → 409."""
    result = await ops_svc.move_student(
        db, school_id, user_id, body.class_id, actor_user_id=current.id
    )
    await db.commit()
    return result


@router.get("/school/{school_id}/staff")
async def get_school_staff(
    school_id: int,
    current: AuthUser = Depends(require_permission("view_students", scope_type="school", scope_param="school_id")),
    db: AsyncSession = Depends(get_db),
):
    """کادر آموزشی: کلاس/درس هر معلم + شیفت و بار هفتگی استخراج‌شده از برنامه."""
    return await ops_svc.staff(db, school_id)
