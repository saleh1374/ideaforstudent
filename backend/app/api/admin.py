"""Admin APIs (school admin spec + district spec + RBAC spec §16-18):
aggregated overviews, employment request inbox, permission grant/revoke."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthUser, get_current_user, require_permission
from app.core.db import get_db
from app.models.assessment import AttemptAnswer, Exam, ExamAttempt
from app.models.employment import EmploymentPolicyRule, EmploymentRequest
from app.models.org import School, StudentProfile, User
from app.models.rbac import Permission, PermissionAssignment, Role
from app.models.slm import StudentTopicState
from app.services.employment import decide_request, submit_teacher_request
from app.services.rbac_service import effective_permissions, grant_permission, revoke_permission, user_scopes
from datetime import date

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/school/{school_id}/overview")
async def school_overview(
    school_id: int,
    current: AuthUser = Depends(require_permission("view_school_analytics")),
    db: AsyncSession = Depends(get_db),
):
    """داشبورد کلان مدرسه: میانگین تسلط، نیازمندان مداخله، وضعیت کلاس‌ها.
    همه اعداد از همان هسته SLM تجمیع می‌شوند (spec: «هیچ‌کدام از این پنل‌ها
    لایه داده جدا نمی‌سازند»)."""
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


@router.get("/employment-requests")
async def list_employment_requests(
    current: AuthUser = Depends(require_permission("manage_employment")),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(select(EmploymentRequest).order_by(EmploymentRequest.created_at.desc()))
    ).scalars().all()
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
    """قاعده طلایی در بک‌اند اعمال می‌شود نه فقط UI (RBAC spec §8)."""
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
    await db.commit()
    return result


@router.post("/permissions/{assignment_id}/revoke")
async def revoke(
    assignment_id: int,
    current: AuthUser = Depends(require_permission("manage_permissions")),
    db: AsyncSession = Depends(get_db),
):
    result = await revoke_permission(db, actor_user_id=current.id, assignment_id=assignment_id)
    await db.commit()
    return result


@router.get("/permissions/mine")
async def my_permissions(current: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    keys = await effective_permissions(db, current.id)
    scopes = await user_scopes(db, current.id)
    return {"permissions": sorted(keys), "scopes": scopes}
