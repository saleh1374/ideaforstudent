"""Employment approval workflow service (RBAC spec §5)."""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employment import EmploymentPolicyRule, EmploymentRequest
from app.models.org import Employment, Employee, School, SchoolAssignment
from app.services.rbac_service import log_action


async def check_policy(db: AsyncSession, *, school: School, employment_type: str) -> dict:
    """Returns {requires_approval: bool, rule_found: bool}."""
    rule = (
        await db.execute(
            select(EmploymentPolicyRule).where(
                EmploymentPolicyRule.school_ownership == school.ownership_type,
                EmploymentPolicyRule.employment_type == employment_type,
            )
        )
    ).scalar_one_or_none()
    if rule is None:
        # fail-safe: unknown combination requires approval
        return {"requires_approval": True, "rule_found": False}
    return {"requires_approval": rule.requires_district_approval, "rule_found": True}


async def submit_teacher_request(
    db: AsyncSession,
    *,
    school_id: int,
    requested_by: int,
    employee_user_id: int,
    full_name: str,
    employment_type: str,
    organization: str = "government",
    subject: str | None = None,
    start_date: date | None = None,
) -> dict:
    """Step 1-4 of spec fig.4: principal submits; system checks policy; if a
    policy row says no approval needed → auto-approve, else send to district."""
    school = await db.get(School, school_id)
    if school is None:
        return {"ok": False, "reason": "مدرسه یافت نشد"}

    policy = await check_policy(db, school=school, employment_type=employment_type)
    status = "auto_approved" if not policy["requires_approval"] else "pending"

    req = EmploymentRequest(
        school_id=school_id,
        requested_by=requested_by,
        employee_user_id=employee_user_id,
        full_name=full_name,
        employment_type=employment_type,
        organization=organization,
        subject=subject,
        status=status,
        decided_at=datetime.now(timezone.utc) if status == "auto_approved" else None,
        decision_note="طبق سیاست استخدام، نیاز به تأیید ناحیه نداشت" if status == "auto_approved" else None,
    )
    db.add(req)
    await db.flush()

    await log_action(
        db,
        actor_user_id=requested_by,
        action="employment_request_submitted",
        entity_type="employment_request",
        entity_id=req.id,
        detail=f"school={school_id} type={employment_type} status={status}",
    )

    if status == "auto_approved":
        await _activate(db, req=req, start_date=start_date or date.today())

    return {"ok": True, "request_id": req.id, "status": status, "policy_rule_found": policy["rule_found"]}


async def _activate(db: AsyncSession, *, req: EmploymentRequest, start_date: date) -> None:
    """Creates Employee/Employment/SchoolAssignment chain on approval."""
    emp = (
        await db.execute(select(Employee).where(Employee.user_id == req.employee_user_id))
    ).scalar_one_or_none()
    if emp is None:
        emp = Employee(user_id=req.employee_user_id)
        db.add(emp)
        await db.flush()

    empl = Employment(
        employee_id=emp.id,
        employment_type=req.employment_type,
        organization=req.organization,
        start_date=start_date,
        status="active",
    )
    db.add(empl)

    assign = SchoolAssignment(
        employee_id=emp.id,
        school_id=req.school_id,
        role=req.role,
        subject=req.subject,
        start_date=start_date,
        status="active",
    )
    db.add(assign)


async def decide_request(
    db: AsyncSession,
    *,
    decider_user_id: int,
    request_id: int,
    approve: bool,
    note: str | None = None,
    start_date: date | None = None,
) -> dict:
    """District review (spec fig.4 steps 5-6)."""
    req = await db.get(EmploymentRequest, request_id)
    if req is None or req.status != "pending":
        return {"ok": False, "reason": "درخواست یافت نشد یا قبلاً تصمیم‌گیری شده"}

    req.decided_by = decider_user_id
    req.decided_at = datetime.now(timezone.utc)
    req.decision_note = note
    req.status = "approved" if approve else "rejected"

    await log_action(
        db,
        actor_user_id=decider_user_id,
        action="employment_request_approved" if approve else "employment_request_rejected",
        entity_type="employment_request",
        entity_id=req.id,
        detail=f"school={req.school_id} note={note or ''}",
    )

    if approve:
        await _activate(db, req=req, start_date=start_date or date.today())

    return {"ok": True, "status": req.status}
