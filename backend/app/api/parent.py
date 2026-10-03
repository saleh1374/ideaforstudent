"""Parent panel APIs (roadmap phase 5، سند پنل والدین §17).

والد فقط فرزندان متصل‌شده (ParentLink) را می‌بیند؛ داده تجمیعی و بدون
مقایسه با دانش‌آموزان دیگر — اصل حفظ حریم خصوصی کودک."""
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthUser, get_current_user
from app.core.db import get_db
from app.models import parent_reports  # noqa: F401  (ثبت جدول کش گزارش هفتگی)
from app.models import parent_panel  # noqa: F401  (ثبت جدول‌های پنل والدین)
from app.models.org import ParentLink, StudentProfile, User
from app.models.parent_panel import ParentLinkPermission, TutorSatisfaction
from app.models.parent_reports import ParentWeeklyReport
from app.models.slm import ErrorRecord
from app.services import parent_reports as reports
from app.services import tutoring as tutoring_svc
from app.services.rbac_service import log_action
from app.services.slm import status_of

router = APIRouter(prefix="/parent", tags=["parent"])

# کلیدهای مجوزِ مستقلِ هر پیوند والد–فرزند (سند §17) — نبودِ ردیف یعنی مجاز
LINK_PERMISSIONS: dict[str, str] = {
    "class_comparison": "مقایسه با میانگین کالس (§4)",
    "attendance": "حضور و جلسات (§9)",
    "assistant": "دستیار هوشمند والد (§15)",
    "tutor_market": "بازار معلم خصوصی (§11)",
    "exam_results": "گزارش نمرات آزمون‌ها (§3)",
    "weekly_report": "گزارش هفتگی (§14)",
}


async def _my_children(db: AsyncSession, parent_id: int) -> list[User]:
    links = (
        await db.execute(
            select(ParentLink).where(
                ParentLink.parent_user_id == parent_id, ParentLink.status == "active"
            )
        )
    ).scalars().all()
    if not links:
        return []
    ids = [l.student_user_id for l in links]
    return list((await db.execute(select(User).where(User.id.in_(ids)))).scalars())


async def _active_link(db: AsyncSession, parent_id: int, student_id: int) -> ParentLink:
    link = (
        await db.execute(
            select(ParentLink).where(
                ParentLink.parent_user_id == parent_id,
                ParentLink.student_user_id == student_id,
                ParentLink.status == "active",
            )
        )
    ).scalar_one_or_none()
    if link is None:
        raise HTTPException(403, "این دانش‌آموز به شما متصل نیست")
    return link


async def _require_child(db: AsyncSession, parent_id: int, student_id: int) -> None:
    """همه‌ی endpointهای فرزند ابتدا پیوند فعال والد–فرزند را می‌سنجد؛
    بدون پیوند ⇒ 403 (سند §17، همان پیام و کد موجود برای overview)."""
    await _active_link(db, parent_id, student_id)


async def _link_allows(db: AsyncSession, parent_id: int, student_id: int, key: str) -> bool:
    """مجوزِ این کلید برای این پیوند (§17): نبودِ ردیف یعنی «مجاز» — پیش‌ردیف
    دسترسی کامل، پس پیوندهای موجودِ seed رفتارشان تغییر نمی‌کند."""
    link = await _active_link(db, parent_id, student_id)
    row = (
        await db.execute(
            select(ParentLinkPermission).where(
                ParentLinkPermission.link_id == link.id,
                ParentLinkPermission.key == key,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return True
    return bool(row.allowed)


async def _require_link_key(db: AsyncSession, parent_id: int, student_id: int, key: str) -> None:
    """علاوه بر پیوند، مجوزِ خودِ پیوند را هم می‌سنجد (۴۰۳ با پیام روشن)."""
    if not await _link_allows(db, parent_id, student_id, key):
        raise HTTPException(403, f"دسترسی برای این فرزند محدود شده است: {LINK_PERMISSIONS.get(key, key)}")


@router.get("/children")
async def children(current: AuthUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    users = await _my_children(db, current.id)
    out = []
    for u in users:
        profile = (
            await db.execute(select(StudentProfile).where(StudentProfile.user_id == u.id))
        ).scalar_one_or_none()
        out.append(
            {
                "id": u.id,
                "full_name": u.full_name,
                "grade": profile.grade if profile else None,
                "class_id": profile.class_id if profile else None,
            }
        )
    return {"children": out}


@router.get("/children/{student_id}/overview")
async def child_overview(
    student_id: int,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """نمای کلان فرزند: دو شاخص جدا (پیشرفت ≠ تسط) + وضعیت مباحث + خطاهای باز.
    بدون رتبه و بدون مقایسه با هم‌کلاسی‌ها (سند والدین)."""
    await _require_child(db, current.id, student_id)

    # دو شاخص و توزیع وضعیت مباحث از همان سرویس گزارش‌ها می‌آید تا عدد
    # overview، هشدارها و گزارش هفتگی همیشه با هم هم‌راستا باشند.
    pm = await reports.progress_mastery(db, student_id)
    topics = pm["topics"]

    errors = (
        await db.execute(select(ErrorRecord).where(ErrorRecord.student_user_id == student_id))
    ).scalars().all()
    # حل‌نشده = باز یا در چرخه ترمیم یا بازگشته
    open_errors = [e for e in errors if e.status in ("open", "in_remediation", "relapsed")]

    weak_topics = []
    for st in pm["states"]:
        k = status_of(st.effective_mastery, st.evidence_count)
        if k in ("weak", "critical") and len(weak_topics) < 5 and st.topic_id in topics:
            weak_topics.append({"topic_id": st.topic_id, "title": topics[st.topic_id].title_fa, "status": k})

    gap = pm["gap"]
    advice = None
    if abs(gap) >= 15 and gap > 0:
        advice = "خوانده ولی جا نیفتاده — مرور فاصله‌دار و بسته ترمیمی اولویت دارد."
    elif abs(gap) >= 15 and gap < 0:
        advice = "تسلط بالاست ولی عقب‌ماندگی برنامه داریم — سرعت پیشروی بررسی شود."
    elif open_errors:
        advice = f"{len(open_errors)} خطای باز دارد؛ بازآزمون ترمیمی پیشنهاد می‌شود."

    return {
        "student_id": student_id,
        "progress_pct": pm["progress_pct"],
        "mastery_pct": pm["mastery_pct"],
        "gap": gap,
        "gap_message": advice,
        "errors_total": len(errors),
        "errors_open": len(open_errors),
        "status_counts": pm["status_counts"],
        "weak_topics": weak_topics,
        "note_fa": "مقایسه با دانش‌آموزان دیگر نمایش داده نمی‌شود؛ این نمای انحصاری فرزند شماست.",
    }


# ------------------------------------------------------- سند §3: نمرات آزمون‌ها


@router.get("/children/{student_id}/exam-results")
async def child_exam_results(
    student_id: int,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """نمره، درصد، صحیح/غلط/نزده، نمره منفی و زمان هر آزمون + روند (§3)."""
    await _require_link_key(db, current.id, student_id, "exam_results")
    return await reports.exam_results(db, student_id)


@router.get("/children/{student_id}/exam-results/{attempt_id}")
async def child_exam_result_detail(
    student_id: int,
    attempt_id: int,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """جزئیات یک نتیجه: وضعیت هر مبحث، نوع خطاها و سؤال‌های نادرست (§3)."""
    await _require_link_key(db, current.id, student_id, "exam_results")
    try:
        return await reports.exam_result_detail(db, student_id, attempt_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


# --------------------------------------- سند §6/§8: برنامه و تکلیف (فقط‌خواندنی)


@router.get("/children/{student_id}/plan")
async def child_plan(
    student_id: int,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """برنامه/تکلیف فقط‌خواندنی + موعدها + بازه‌ی آزمون پیش رو (§6، §8)."""
    await _require_child(db, current.id, student_id)
    return await reports.plan_view(db, student_id)


# ------------------------------------------------- سند §13: هشدار هوشمند والد


@router.get("/children/{student_id}/alerts")
async def child_alerts(
    student_id: int,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """هشدارهای قاعده‌محور والد — فقط سیگنال‌های خودِ فرزند، بدون مقایسه (§13)."""
    await _require_child(db, current.id, student_id)
    alerts = await reports.build_alerts(db, student_id)
    return {
        "student_id": student_id,
        "alerts": alerts,
        "counts": {
            "danger": sum(1 for a in alerts if a["severity"] == "danger"),
            "warning": sum(1 for a in alerts if a["severity"] == "warning"),
            "info": sum(1 for a in alerts if a["severity"] == "info"),
            "total": len(alerts),
        },
        "thresholds": {
            "gap_units": reports.GAP_ALERT_UNITS,
            "inactive_days": reports.INACTIVE_DAYS,
            "repeat_error_min": reports.REPEAT_ERROR_MIN,
        },
        "note_fa": "هشدارها فقط از داده‌های همین فرزند و با قواعد قطعی ساخته می‌شوند؛ "
        "بدون رتبه و بدون مقایسه با فرزندان دیگر.",
    }


# ------------------------------------------------- سند §14: گزارش هفتگی والد


@router.get("/children/{student_id}/weekly-report")
async def child_weekly_report(
    student_id: int,
    refresh: bool = False,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """گزارش هفتگی تجمیعی فرزند (§14) — کش هفتگیِ idempotent؛ refresh=1 بازسازی."""
    await _require_link_key(db, current.id, student_id, "weekly_report")

    # نخست کش همین هفته را ببین؛ فقط در صورت نبودِ ردیف (یا درخواست تازه‌سازی)
    # گزارش ساخته می‌شود — محاسبه‌ی تکراری انجام نمی‌شود.
    week_start = reports.week_bounds(date.today())[0]
    row = (
        await db.execute(
            select(ParentWeeklyReport).where(
                ParentWeeklyReport.parent_user_id == current.id,
                ParentWeeklyReport.student_user_id == student_id,
                ParentWeeklyReport.week_start == week_start,
            )
        )
    ).scalar_one_or_none()
    if row is not None and not refresh:
        return {**row.payload, "cached": True}

    _week_start, payload = await reports.build_weekly_report(db, student_id)
    generated_at = datetime.fromisoformat(payload["generated_at"])
    if row is None:
        db.add(
            ParentWeeklyReport(
                parent_user_id=current.id,
                student_user_id=student_id,
                week_start=week_start,
                generated_at=generated_at,
                payload=payload,
            )
        )
    else:
        row.payload = payload
        row.generated_at = generated_at

    # تنها تغییر وضعیتِ این بخش: ساخت/تازه‌سازی گزارش ⇒ ثبت ممیزی (§ضمیمه ب)
    await log_action(
        db,
        actor_user_id=current.id,
        action="weekly_report_generated",
        entity_type="student",
        entity_id=student_id,
        detail=f"week={week_start.isoformat()} refresh={int(refresh)}",
    )
    await db.commit()
    return {**payload, "cached": False}


# ---------------------------------------------- سند §2: وضعیت یادگیری


@router.get("/children/{student_id}/subjects")
async def child_subjects(
    student_id: int,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """وضعیت هر درس با روند + مباحث نیازمند توجه و نقاط قوت، تا سطح مبحث (§2)."""
    await _require_child(db, current.id, student_id)
    return await reports.subject_status(db, student_id)


# ---------------------------------------------- سند §4: سه نوع مقایسه


@router.get("/children/{student_id}/comparisons")
async def child_comparisons(
    student_id: int,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """سه مقایسه (خودش / هدف دوره / کالس) — کالس فقط اگر مجوزِ پیوند مجاز
    کرده باشد و جمعیت کالس از حداقل جمعیت بگذرد (§4 + §17)."""
    await _require_child(db, current.id, student_id)
    class_allowed = await _link_allows(db, current.id, student_id, "class_comparison")
    return await reports.comparisons(db, student_id, class_allowed=class_allowed)


# ---------------------------------------------- سند §9: حضور و جلسات


@router.get("/children/{student_id}/attendance")
async def child_attendance(
    student_id: int,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """حضور مدرسه + جلسات گذشته/آینده با گزارش و تکلیف (§9)."""
    await _require_link_key(db, current.id, student_id, "attendance")
    return await reports.attendance_and_sessions(db, student_id)


# ------------------------------- سند §15: دستیار هوشمند والد (Parent Copilot)


class AssistantIn(BaseModel):
    question: str


@router.post("/children/{student_id}/assistant")
async def child_assistant(
    student_id: int,
    body: AssistantIn,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """پاسخ دستیار فقط بر پایه‌ی داده‌ی واقعی همین فرزند (§15) — قاعده‌محور،
    بدون قضاوت شخصیتی، با ثبت ممیزی parent_copilot_query."""
    await _require_link_key(db, current.id, student_id, "assistant")
    try:
        result = await reports.assistant_answer(db, student_id, body.question)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await log_action(
        db,
        actor_user_id=current.id,
        action="parent_copilot_query",
        entity_type="student",
        entity_id=student_id,
        detail=f"intent={result['intent']} len={len(result['question'])}",
    )
    await db.commit()
    return result


# ------------------------------- سند §17: مجوزهای هر پیوند والد–فرزند


async def _link_or_403(db: AsyncSession, parent_id: int, link_id: int) -> ParentLink:
    link = await db.get(ParentLink, link_id)
    if link is None or link.parent_user_id != parent_id or link.status != "active":
        raise HTTPException(404, "پیوند والد–فرزند یافت نشد")
    return link


@router.get("/links")
async def my_links(
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """پیوندهای فعال این والد + مجوزهای هر پیوند (§17) — مبنای سوییچ فرزند."""
    links = (
        (
            await db.execute(
                select(ParentLink).where(
                    ParentLink.parent_user_id == current.id, ParentLink.status == "active"
                )
            )
        )
        .scalars()
        .all()
    )
    out = []
    for link in links:
        perms = {
            p.key: bool(p.allowed)
            for p in (
                (
                    await db.execute(
                        select(ParentLinkPermission).where(ParentLinkPermission.link_id == link.id)
                    )
                ).scalars()
            )
        }
        student = await db.get(User, link.student_user_id)
        out.append(
            {
                "link_id": link.id,
                "student_user_id": link.student_user_id,
                "student_name": student.full_name if student else None,
                "relation": link.relation,
                # نبودِ ردیف = مجاز؛ خروجی همه‌ی کلیدها را صریح برمی‌گردانیم
                "permissions": {key: perms.get(key, True) for key in LINK_PERMISSIONS},
                "overridden_keys": sorted(perms),
            }
        )
    return {"links": out, "permission_keys": LINK_PERMISSIONS}


class LinkPermissionsIn(BaseModel):
    permissions: dict[str, bool]


@router.patch("/links/{link_id}/permissions")
async def set_link_permissions(
    link_id: int,
    body: LinkPermissionsIn,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """تنظیم مجوزِ یک پیوند (§17): هر پیوند مجوز مستقل دارد؛ مقدار false یعنی
    محدودسازی دسترسی همان فرزند — فقط توسط خودِ والدِ همان پیوند."""
    link = await _link_or_403(db, current.id, link_id)
    unknown = [k for k in body.permissions if k not in LINK_PERMISSIONS]
    if unknown:
        raise HTTPException(400, f"کلید مجوز نامعتبر: {', '.join(sorted(unknown))}")

    changed = []
    for key, allowed in body.permissions.items():
        row = (
            await db.execute(
                select(ParentLinkPermission).where(
                    ParentLinkPermission.link_id == link.id,
                    ParentLinkPermission.key == key,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            db.add(
                ParentLinkPermission(
                    link_id=link.id, key=key, allowed=1 if allowed else 0, updated_by=current.id
                )
            )
        else:
            row.allowed = 1 if allowed else 0
            row.updated_by = current.id
            row.updated_at = datetime.utcnow()
        changed.append(key)
    await db.flush()
    await log_action(
        db,
        actor_user_id=current.id,
        action="parent_link_permission_updated",
        entity_type="parent_link",
        entity_id=link.id,
        detail=f"student={link.student_user_id} keys={','.join(sorted(changed))}",
    )
    await db.commit()

    perms = {
        p.key: bool(p.allowed)
        for p in (
            (
                await db.execute(
                    select(ParentLinkPermission).where(ParentLinkPermission.link_id == link.id)
                )
            ).scalars()
        )
    }
    return {
        "ok": True,
        "link_id": link.id,
        "student_user_id": link.student_user_id,
        "permissions": {key: perms.get(key, True) for key in LINK_PERMISSIONS},
    }


# ----------------------- سند §11/§12: معلم خصوصی از دید والد


@router.get("/tutors")
async def parent_tutor_market(
    subject: str | None = None,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """بازار معلم‌ها از زاویه دید والد (§11) — همان داده‌ی بازار با فیلتر درس؛
    دسترسی با کلید مجوزِ پیوندِ هیچ فرزندی گره نمی‌خورد چون فهرست عمومی است."""
    data = await tutoring_svc.market_list(db, subject)
    return {
        **data,
        "total": len(data.get("tutors", [])),
        "note_fa": (
            "مسیر درخواست، پذیرش معلم، گروه/چت خصوصی، تقویم و گزارش جلسه همان جریان "
            "بخش ۲.۱۰ سند دانش‌آموز است؛ والد در این نما فقط جست‌وجو و انتخاب می‌کند (§11)."
        ),
    }


class SatisfactionIn(BaseModel):
    student_user_id: int
    tutor_user_id: int
    rating: int
    comment: str | None = None


@router.post("/tutor-satisfaction")
async def save_tutor_satisfaction(
    body: SatisfactionIn,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """ثبت امتیاز/بازخورد والد از معلم خصوصیِ همین فرزند (§11/§12) — سیگنال
    رضایت، جدا از داده‌ی آموزشی و فقط از دید همان والد."""
    if body.rating < 1 or body.rating > 5:
        raise HTTPException(400, "امتیاز باید بین ۱ تا ۵ باشد")
    await _require_child(db, current.id, body.student_user_id)
    tutor = await db.get(User, body.tutor_user_id)
    if tutor is None or tutor.system_role != "teacher":
        raise HTTPException(404, "معلم یافت نشد")

    row = (
        await db.execute(
            select(TutorSatisfaction).where(
                TutorSatisfaction.parent_user_id == current.id,
                TutorSatisfaction.student_user_id == body.student_user_id,
                TutorSatisfaction.tutor_user_id == body.tutor_user_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = TutorSatisfaction(
            parent_user_id=current.id,
            student_user_id=body.student_user_id,
            tutor_user_id=body.tutor_user_id,
            rating=body.rating,
            comment=body.comment,
        )
        db.add(row)
    else:
        row.rating = body.rating
        row.comment = body.comment
    await db.flush()
    await log_action(
        db,
        actor_user_id=current.id,
        action="tutor_satisfaction_saved",
        entity_type="tutor",
        entity_id=body.tutor_user_id,
        detail=f"student={body.student_user_id} rating={body.rating}",
    )
    await db.commit()
    return {"ok": True, "rating": row.rating, "comment": row.comment}


@router.get("/tutor-satisfaction")
async def list_tutor_satisfaction(
    student_user_id: int,
    current: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """امتیازهای ثبت‌شده‌ی همین والد برای فرزند انتخابی (§12)."""
    await _require_child(db, current.id, student_user_id)
    rows = (
        (
            await db.execute(
                select(TutorSatisfaction).where(
                    TutorSatisfaction.parent_user_id == current.id,
                    TutorSatisfaction.student_user_id == student_user_id,
                )
            )
        )
        .scalars()
        .all()
    )
    out = []
    for r in rows:
        tutor = await db.get(User, r.tutor_user_id)
        out.append(
            {
                "tutor_user_id": r.tutor_user_id,
                "tutor_name": tutor.full_name if tutor else None,
                "rating": r.rating,
                "comment": r.comment,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
        )
    return {"student_user_id": student_user_id, "rows": out}
