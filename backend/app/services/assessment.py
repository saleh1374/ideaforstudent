"""Assessment service: grading, error-cause classification, org snapshot,
evidence feed, and error-record lifecycle (student spec §5, §6)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.assessment import AttemptAnswer, Exam, ExamAttempt, ExamItem, QuestionFamilyMember
from app.models.org import School, StudentProfile
from app.models.slm import ErrorRecord, Evidence
from app.services import slm

# شش علت خطا (§6.1) + برچسب «نامشخص» وقتی قطعیت تشخیص کم است (§6.2)
SIX_CAUSES = ("conceptual", "prerequisite", "calculation", "careless", "time_management", "guess")
UNCLEAR_CAUSE = "unclear"

# برچسب فارسی علت‌ها برای پیام‌های API دانش‌آموز (نمایش دفترچه خطا)
CAUSE_FA = {
    "conceptual": "ضعف مفهومی",
    "prerequisite": "کمبود دانش / پیش‌نیاز",
    "calculation": "خطای محاسباتی / روشی",
    "careless": "بی‌دقتی",
    "time_management": "کمبود زمان",
    "guess": "حدس",
    "unclear": "علت نامشخص — از شما پرسیده می‌شود",
}

# زمان مورد انتظار هر سؤال (§5.3 expected_time) — مبنای تایمر سؤال در §5.6
# و نسبت زمان در تشخیص علت خطا (§6.2). بدون ستون جدید؛ از روی دشواری ساخته می‌شود.
EXPECTED_TIME_MS = {"easy": 60_000, "medium": 90_000, "hard": 120_000}


def expected_time_ms(difficulty: str | None) -> int:
    """زمان مجاز/مورد انتظار هر سؤال بر حسب ثانیه — منبع سمت سرور."""
    return EXPECTED_TIME_MS.get(difficulty or "medium", EXPECTED_TIME_MS["medium"])


def classify_error_detailed(
    *,
    is_correct: bool,
    time_spent_ms: int,
    confidence: int | None,
    selected: str | None,
    correct_option: str,
    item_distractor_causes: dict | None,
    flagged_guess: bool,
    difficulty: str = "medium",
    lesson_completed: bool = False,
    prereq_mastery: float | None = None,
) -> dict:
    """تشخیص علت خطا با ترکیب چند سیگنال + «قطعیت» (student spec §6.2):

        scores = {…};  cause = argmax(scores);  certainty = scores[cause]/Σscores
        if certainty < 0.5:  cause = "unclear"   → از دانش‌آموز پرسیده می‌شود

    خروجی:
      cause          یکی از ۶ علت یا «unclear» (برای ثبت در دفترچه خطا)
      predicted_cause همیشه یکی از ۶ علت (ماکزیمم امتیاز؛ حداکثری = conceptual)
      certainty      نسبت امتیاز علت برتر به کل امتیازها (۰ تا ۱)
      unclear        آیا قطعیت زیر ۰.۵ است و باید از دانش‌آموز پرسیده شود
      scores         امتیاز هر علت (برای تحلیل/نمایش)
    """
    if is_correct:
        return {
            "cause": None,
            "predicted_cause": None,
            "certainty": 1.0,
            "scores": {},
            "unclear": False,
        }

    s = get_settings()
    unanswered = selected is None
    conf = confidence
    prereq = prereq_mastery
    mapped = (item_distractor_causes or {}).get(selected or "")
    time_ratio = time_spent_ms / float(expected_time_ms(difficulty)) if time_spent_ms else 0.0

    scores: dict[str, float] = {c: 0.0 for c in SIX_CAUSES}

    # — سیگنال‌های بند ۶.۲ سند —
    # بی‌پاسخ یا عجله در پایان زمان ⇒ کمبود زمان
    if unanswered or time_spent_ms >= s.slow_answer_ms:
        scores["time_management"] += 3
    # اطمینان «حدس زدم»
    if flagged_guess or conf == 1:
        scores["guess"] += 3
    # نگاشت گزینهٔ غلطِ انتخاب‌شده به کج‌فهمی/لغزش (مهم‌ترین سیگنال)
    if mapped in scores:
        if mapped == "conceptual" and conf is not None and conf < 2:
            scores["conceptual"] += 1  # اطمینان پایین ⇒ شاهد ضعیف‌تر
        else:
            scores[mapped] += 3
    # پاسخ غلط با اطمینان بالا ⇒ بی‌دقتی (قاعدهٔ قدیمی نسخهٔ اول)
    if mapped is None and conf is not None and conf >= s.low_confidence + 2:
        scores["careless"] += 2
    # سؤال آسانِ خیلی سریع با پیش‌نیاز مسلط ⇒ بی‌دقتی
    if (
        difficulty == "easy"
        and 0 < time_ratio < 0.3
        and prereq is not None
        and prereq >= 70
    ):
        scores["careless"] += 3
    # درس‌نامه تکمیل نشده یا تسلط پیش‌نیاز زیر ۳۰ ⇒ کمبود دانش
    if not lesson_completed or (prereq is not None and prereq < 30):
        scores["prerequisite"] += 3

    total = sum(scores.values())
    if total <= 0:
        # هیچ سیگنالی نداریم ⇒ پیش‌بینی پیش‌فرض مفهومی، ولی قطعیت صفر ⇒ نامشخص
        predicted = "conceptual"
        certainty = 0.0
        cause = UNCLEAR_CAUSE
    else:
        # نگاشت صریح گزینهٔ غلط مهم‌ترین سیگنال است (در تساوی امتیاز برنده است)
        order = list(SIX_CAUSES)
        if mapped in scores:
            order = [mapped] + [c for c in order if c != mapped]
        predicted = max(order, key=lambda c: scores[c])
        certainty = round(scores[predicted] / total, 3)
        cause = UNCLEAR_CAUSE if certainty < 0.5 else predicted

    return {
        "cause": cause,
        "predicted_cause": predicted,
        "certainty": certainty,
        "scores": {k: v for k, v in scores.items() if v},
        "unclear": cause == UNCLEAR_CAUSE,
    }


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
    conceptual | prerequisite | calculation | careless | time_management | guess

    نسخهٔ سادهٔ سازگار با قبل (فقط علت پیش‌بینی‌شده)؛ نسخهٔ کامل با
    «قطعیت» و «نامشخص» در classify_error_detailed است."""
    return classify_error_detailed(
        is_correct=is_correct,
        time_spent_ms=time_spent_ms,
        confidence=confidence,
        selected=selected,
        correct_option=correct_option,
        item_distractor_causes=item_distractor_causes,
        flagged_guess=flagged_guess,
    )["predicted_cause"]


# ------------------------------------------- بخش الف/ب آزمون تجمعی (§5.1)
SECTION_FA = {"A": "بخش الف — استاندارد", "B": "بخش ب — شخصی"}


def assign_sections(exam: Exam, exam_items: list[ExamItem], error_topic_ids: set[int]) -> dict[int, str]:
    """نگاشت هر سؤال به بخش «الف» یا «ب» (student spec §5.1 آزمون تجمعی):

      بخش الف: استاندارد و یکسان برای همه ⇒ در بردها حساب می‌شود.
      بخش ب: شخصی — سؤال‌هایی از مباحثی که همین دانش‌آموز قبلاً در آن‌ها خطا
      داشته (صورت/سطح متفاوت)؛ در برد نیست و فقط SLM را به‌روز می‌کند.

    آزمون غیرتجمعی تک‌بخشی است (همه «الف»). اگر همهٔ سؤال‌ها در مباحث
    خطادار باشند، حداکثر نصف آن‌ها به بخش ب می‌روند تا بخش الف استاندارد
    بماند. نگاشت قطعی و از روی دادهٔ خود دانش‌آموز است؛ نیازی به ذخیره ندارد."""
    if exam.exam_type != "cumulative":
        return {ei.id: "A" for ei in exam_items}
    ordered = sorted(exam_items, key=lambda ei: ei.order)
    personal = [
        ei for ei in ordered
        if ei.item is not None and ei.item.topic_id in error_topic_ids
    ]
    limit = max(1, len(ordered) // 2) if len(ordered) > 1 else 0
    personal_ids = {ei.id for ei in personal[:limit]}
    return {ei.id: ("B" if ei.id in personal_ids else "A") for ei in ordered}


def section_summary(exam: Exam) -> dict:
    """خلاصهٔ بخش‌ها برای فهرست آزمون‌ها (برچسب UI: «دو بخش الف/ب»)."""
    if exam.exam_type != "cumulative":
        return {"two_sections": False, "sections": []}
    return {
        "two_sections": True,
        "sections": [
            {"key": "A", "title_fa": SECTION_FA["A"], "counts_for_board": True},
            {"key": "B", "title_fa": SECTION_FA["B"], "counts_for_board": False},
        ],
        "note_fa": "بخش الف برای همه یکسان است و وارد بردها می‌شود؛ بخش ب شخصی است و فقط تسط را به‌روز می‌کند.",
    }


# -------------------------------------- گروه سؤال‌های هم‌ارز family_id (§5.3)
def family_key_for(q) -> str:
    """family_id پیش‌فرض: یک مهارت + یک سطح دشواری ⇒ یک خانوادهٔ هم‌ارز."""
    return f"F{q.topic_id}-{q.skill_id or 0}-{q.difficulty or 'medium'}"


async def ensure_question_families(db: AsyncSession, items: list) -> dict[int, str]:
    """عضویت سؤال‌های هم‌ارز را (بدون تکرار، idempotent) ثبت می‌کند و
    family_id هر سؤال را برمی‌گرداند — ورودی انتخاب سؤال بازآزمون (§5.8)."""
    if not items:
        return {}
    ids = [q.id for q in items]
    existing = {
        row.item_id: row.family_id
        for row in (
            await db.execute(select(QuestionFamilyMember).where(QuestionFamilyMember.item_id.in_(ids)))
        ).scalars()
    }
    out = dict(existing)
    for q in items:
        if q.id in out:
            continue
        key = family_key_for(q)
        db.add(QuestionFamilyMember(family_id=key, item_id=q.id))
        out[q.id] = key
    return out


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

    # ---- زمینهٔ تشخیص علت (§6.2): پیش‌نیازها + تسلطشان + اتمام درس‌نامه ----
    from app.models.catalog import Prerequisite
    from app.models.slm import PlanTask, StudentTopicState

    topic_ids = {q.topic_id for q in questions.values()}
    prereqs_by_topic: dict[int, list[int]] = {}
    if topic_ids:
        for pre in (
            await db.execute(select(Prerequisite).where(Prerequisite.topic_id.in_(topic_ids)))
        ).scalars():
            prereqs_by_topic.setdefault(pre.topic_id, []).append(pre.prereq_topic_id)
    states = {
        st.topic_id: st.effective_mastery
        for st in (
            await db.execute(
                select(StudentTopicState).where(StudentTopicState.student_user_id == attempt.student_user_id)
            )
        ).scalars()
    }
    lesson_done = {
        t.topic_id
        for t in (
            await db.execute(
                select(PlanTask).where(
                    PlanTask.student_user_id == attempt.student_user_id,
                    PlanTask.task_type == "lesson",
                    PlanTask.status == "done",
                )
            )
        ).scalars()
        if t.topic_id
    }

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
        # ---- علت خطا + قطعیت تشخیص (§6.2) ----
        pre_ids = prereqs_by_topic.get(q.topic_id) or []
        pre_mastery = (
            min(states.get(pid, 0.0) for pid in pre_ids) if pre_ids else None
        )
        diag = classify_error_detailed(
            is_correct=is_correct,
            time_spent_ms=a.get("time_spent_ms", 0),
            confidence=a.get("confidence"),
            selected=selected,
            correct_option=q.correct_option,
            item_distractor_causes=q.distractor_causes,
            flagged_guess=bool(a.get("flagged_guess")),
            difficulty=q.difficulty,
            lesson_completed=q.topic_id in lesson_done,
            prereq_mastery=pre_mastery,
        )
        # در ردیف پاسخ همیشه یکی از ۶ علت (ماکزیمم امتیاز) ثبت می‌شود تا تحلیل
        # توزیع علت‌ها پابرجا بماند؛ برچسب «نامشخص» در خطا و پاسخ دانش‌آموز است.
        cause = diag["predicted_cause"]
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
                    # «unclear» یعنی قطعیت زیر ۰.۵ بود و باید از دانش‌آموز پرسیده شود؛
                    # علت پیش‌بینی‌شده در item_snapshot می‌ماند (§6.2).
                    cause=diag["cause"] or "conceptual",
                    item_snapshot={
                        "body": q.body,
                        "options": q.options,
                        "correct": q.correct_option,
                        "certainty": diag["certainty"],
                        "predicted_cause": diag["predicted_cause"],
                        "unclear": diag["unclear"],
                        "scores": diag["scores"],
                        "expected_time_ms": expected_time_ms(q.difficulty),
                    },
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
