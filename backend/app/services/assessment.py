"""Assessment service: grading, error-cause classification, org snapshot,
evidence feed, and error-record lifecycle (student spec §5, §6)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.assessment import AttemptAnswer, Exam, ExamAttempt, ExamItem
from app.models.org import School, StudentProfile
from app.models.slm import ErrorRecord, Evidence
from app.services import slm


def classify_error(
    *,
    is_correct: bool,
    time_spent_ms: int,
    confidence: int | None,
    selected: str | None,
    correct_option: str,
    item_distractor_causes: dict | None,
    flagged_guess: bool,
) -> str | None:
    """Six-cause taxonomy (student spec §6):
    conceptual | prerequisite | calculation | careless | time_management | guess"""
    s = get_settings()
    if is_correct:
        return None
    # 1) explicit distractor mapping wins
    if item_distractor_causes and selected in item_distractor_causes:
        return item_distractor_causes[selected]
    # 2) flagged guess
    if flagged_guess:
        return "guess"
    # 3) slow answer => time management
    if time_spent_ms >= s.slow_answer_ms:
        return "time_management"
    # 4) high confidence wrong => careless or conceptual hint
    if confidence is not None and confidence >= s.low_confidence + 2:
        return "careless"
    # 5) default
    return "conceptual"


def grade_answers(answers: list[dict], negative_marking_k: float) -> dict:
    """answers: [{correct: bool, points: float, answered: bool}]
    Returns raw score and percent. Negative marking: wrong answers subtract
    k × points of that item (k configurable per grade, student spec §5.4)."""
    raw = 0.0
    total = 0.0
    for a in answers:
        pts = a["points"]
        total += pts
        if not a.get("answered"):
            continue
        if a["correct"]:
            raw += pts
        else:
            raw -= negative_marking_k * pts
    return {
        "raw_score": round(max(raw, 0.0), 2),
        "percent": round(100.0 * max(raw, 0.0) / total, 2) if total else 0.0,
    }


async def load_student_snapshot(db: AsyncSession, student_user_id: int) -> dict:
    """Org snapshot at submit time: school/class/teacher/district/province
    (student spec §2.11 — «عکس لحظه‌ای ساختار سازمانی روی هر تلاش آزمون»)."""
    from app.models.org import SchoolAssignment

    profile = (
        await db.execute(select(StudentProfile).where(StudentProfile.user_id == student_user_id))
    ).scalar_one_or_none()
    if profile is None:
        return {}
    school = await db.get(School, profile.school_id)
    teacher_id = None
    if profile.class_id:
        from app.models.catalog import Book

        # find active teacher assignment for this school (MVP: first active teacher)
        res = await db.execute(
            select(SchoolAssignment)
            .where(
                SchoolAssignment.school_id == profile.school_id,
                SchoolAssignment.role == "teacher",
                SchoolAssignment.status == "active",
            )
            .limit(1)
        )
        sa = res.scalar_one_or_none()
        teacher_id = sa.employee_id if sa else None
        # map employee_id → user_id
        if sa:
            from app.models.org import Employee

            emp = await db.get(Employee, sa.employee_id)
            teacher_id = emp.user_id if emp else None
    return {
        "school_id": profile.school_id,
        "class_id": profile.class_id,
        "teacher_id": teacher_id,
        "district_id": school.district_id if school else None,
        "province_id": school.province_id if school else None,
    }


EVIDENCE_WEIGHTS = {
    "period_exam": 1.0,
    "cumulative": 1.0,
    "quiz": 0.7,
    "retest": 0.8,
    "remedial_retest": 0.8,
    "practice": 0.5,
    "ai_chat": 0.15,
    "self_report": 0.05,
    "tutoring": 0.5,
}


async def submit_attempt(
    db: AsyncSession,
    *,
    exam: Exam,
    attempt: ExamAttempt,
    answers: list[dict],  # [{exam_item_id, selected, confidence, time_spent_ms, answer_changes, flagged_guess}]
) -> dict:
    """Grades the attempt, writes snapshot answers, error records and SLM
    evidence; returns grading summary."""
    now = datetime.now(timezone.utc)
    settings = get_settings()

    # load exam items + questions (eager: avoid lazy load after flush)
    items = {
        ei.id: ei
        for ei in (
            await db.execute(
                select(ExamItem).options(selectinload(ExamItem.item)).where(ExamItem.exam_id == exam.id)
            )
        ).scalars()
    }
    questions = {}
    for ei in items.values():
        questions[ei.id] = ei.item

    snapshot = await load_student_snapshot(db, attempt.student_user_id)
    grading_rows = []
    answer_rows = []
    evidence_rows = []
    error_rows = []

    for a in answers:
        ei = items.get(a["exam_item_id"])
        if ei is None:
            continue
        q = questions[ei.id]
        selected = a.get("selected")
        is_correct = selected is not None and selected == q.correct_option
        answered = selected is not None
        # ---- error cause ----
        cause = classify_error(
            is_correct=is_correct,
            time_spent_ms=a.get("time_spent_ms", 0),
            confidence=a.get("confidence"),
            selected=selected,
            correct_option=q.correct_option,
            item_distractor_causes=q.distractor_causes,
            flagged_guess=bool(a.get("flagged_guess")),
        )
        answer_rows.append(
            AttemptAnswer(
                attempt_id=attempt.id,
                exam_item_id=ei.id,
                student_user_id=attempt.student_user_id,
                selected_option=selected,
                is_correct=1 if is_correct else 0,
                confidence=a.get("confidence"),
                answer_changes=a.get("answer_changes", 0),
                time_spent_ms=a.get("time_spent_ms", 0),
                question_position=ei.order,
                school_id=snapshot["school_id"],
                class_id=snapshot["class_id"],
                teacher_id=snapshot["teacher_id"],
                district_id=snapshot["district_id"],
                province_id=snapshot["province_id"],
                error_cause=cause,
            )
        )
        grading_rows.append(
            {"correct": is_correct, "points": ei.points, "answered": answered}
        )
        if not is_correct:
            error_rows.append(
                ErrorRecord(
                    student_user_id=attempt.student_user_id,
                    attempt_answer_id=0,  # set after flush
                    topic_id=q.topic_id,
                    skill_id=q.skill_id,
                    cause=cause or "conceptual",
                    item_snapshot={"body": q.body, "options": q.options, "correct": q.correct_option},
                    status="open",
                    created_at=now,
                )
            )
        # evidence per item (partial credit: 1 / 0 / 0.5 for guess-correct)
        c_i = 1.0 if is_correct else 0.0
        if is_correct and a.get("flagged_guess"):
            c_i = 0.5
        evidence_rows.append(
            Evidence(
                student_user_id=attempt.student_user_id,
                topic_id=q.topic_id,
                skill_id=q.skill_id,
                source=exam.exam_type,
                weight=EVIDENCE_WEIGHTS.get(exam.exam_type, 0.5),
                correct=1 if is_correct else 0,
                partial_credit=c_i,
                flagged_guess=1 if a.get("flagged_guess") else 0,
                difficulty_weight=q.difficulty_weight,
                occurred_at=now,
            )
        )

    result = grade_answers(grading_rows, exam.negative_marking_k)
    attempt.raw_score = result["raw_score"]
    attempt.percent = result["percent"]
    attempt.submitted_at = now
    attempt.status = "graded"

    db.add_all(answer_rows)
    await db.flush()  # assign ids to answers

    # link error records to their answers
    for err in error_rows:
        err.attempt_answer_id = answer_rows[error_rows.index(err)].id

    db.add_all(error_rows)
    db.add_all(evidence_rows)
    await db.flush()  # evidence rows must be visible to the SLM updater (autoflush off)

    # update SLM states
    from app.services.slm_service import update_states_from_evidence

    await update_states_from_evidence(db, attempt.student_user_id)

    return result
