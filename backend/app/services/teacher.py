"""Teacher panel services (سند پنل معلم §3, §4, §6):
- رادار مباحث کلاس: تجمیع همان رکوردهای SLM در سطح کلاس (بدون لایه داده جدید)
- ریشه‌یابی: پیمایش گراف پیش‌نیاز تا رسیدن به ریشه ضعف
- گروه‌بندی پنج‌گانه نیاز بر اساس دسته‌بندی §6"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.catalog import Prerequisite, Topic
from app.models.org import ClassRoom, StudentProfile, User
from app.models.slm import ErrorRecord, Evidence, PlanTask, StudentTopicState
from app.services.slm import classify_need, root_cause_decision, status_of, weakest_prereq_index

NEED_FA = {
    "intervention": "مداخله آموزشی",
    "retention_drop": "افت ماندگاری",
    "behind": "عقب‌ماندگی برنامه",
    "future_risk": "ریسک آینده",
    "ready": "آماده پیشروی",
}

NEED_ACTION_FA = {
    "intervention": "بسته ترمیمی فوری، اولویت بالا",
    "retention_drop": "مرور فاصله‌دار",
    "behind": "برنامه جبرانی سبک",
    "future_risk": "پایش، بدون مداخله فوری",
    "ready": "تمرین پیشرفته یا کمک به هم‌کلاسی",
}


async def _class_students(db: AsyncSession, class_id: int) -> list[StudentProfile]:
    return list(
        (await db.execute(select(StudentProfile).where(StudentProfile.class_id == class_id))).scalars()
    )


async def _states_for_students(db: AsyncSession, student_ids: list[int]) -> list[StudentTopicState]:
    if not student_ids:
        return []
    return list(
        (
            await db.execute(
                select(StudentTopicState).where(StudentTopicState.student_user_id.in_(student_ids))
            )
        ).scalars()
    )


async def class_radar(db: AsyncSession, class_id: int) -> dict:
    """رادار مباحث: برای هر مبحث — میانگین تسلط مؤثر، ماندگاری، توزیع علت خطا،
    تعداد نیازمند توجه و پرچم ضعف پیش‌نیاز (سند معلم §3)."""
    students = await _class_students(db, class_id)
    student_ids = [s.user_id for s in students]
    states = await _states_for_students(db, student_ids)
    total_students = len(student_ids)

    by_topic: dict[int, list[StudentTopicState]] = {}
    for st in states:
        by_topic.setdefault(st.topic_id, []).append(st)

    # error distribution per topic (from دفترچه خطا — همان شش علت)
    errors = (
        await db.execute(select(ErrorRecord).where(ErrorRecord.student_user_id.in_(student_ids)))
    ).scalars().all() if student_ids else []
    error_by_topic: dict[int, dict[str, int]] = {}
    for e in errors:
        error_by_topic.setdefault(e.topic_id, {})
        error_by_topic[e.topic_id][e.cause] = error_by_topic[e.topic_id].get(e.cause, 0) + 1

    # prerequisite weakness flags
    prereq_links = (await db.execute(select(Prerequisite))).scalars().all()
    prereqs_of: dict[int, list[int]] = {}
    for p in prereq_links:
        prereqs_of.setdefault(p.topic_id, []).append(p.prereq_topic_id)

    def topic_mean_mastery(topic_id: int) -> float | None:
        rows = by_topic.get(topic_id, [])
        if not rows:
            return None
        return round(sum(r.effective_mastery for r in rows) / len(rows), 1)

    settings = get_settings()
    topics = {t.id: t for t in (await db.execute(select(Topic))).scalars()}
    rows = []
    for topic_id, topic in topics.items():
        topic_states = by_topic.get(topic_id)
        if not topic_states:
            continue  # رادار فقط مباحثی که کلاس رویشان داده دارد
        mean_e = round(sum(r.effective_mastery for r in topic_states) / len(topic_states), 1)
        mean_r = round(sum(r.retention for r in topic_states) / len(topic_states), 3)
        weak_count = sum(1 for r in topic_states if r.effective_mastery < settings.threshold_consolidating)
        prereq_weak = False
        for pid in prereqs_of.get(topic_id, []):
            pm = topic_mean_mastery(pid)
            if pm is not None and pm < settings.prerequisite_mastery_threshold:
                prereq_weak = True
        rows.append(
            {
                "topic_id": topic_id,
                "title": topic.title_fa,
                "avg_mastery": mean_e,
                "avg_retention": mean_r,
                "status": status_of(mean_e, len(topic_states) * settings.evidence_min_for_status),
                "weak_count": weak_count,
                "students_with_data": len(topic_states),
                "total_students": total_students,
                "error_causes": error_by_topic.get(topic_id, {}),
                "prereq_weak": prereq_weak,
            }
        )
    rows.sort(key=lambda r: r["avg_mastery"])
    return {"class_id": class_id, "total_students": total_students, "rows": rows}


async def root_cause_chain(db: AsyncSession, class_id: int, topic_id: int) -> dict:
    """ریشه‌یابی ضعف (سند معلم §4): از مبحث هدف بالا می‌رویم؛ در هر گام اگر
    همه پیش‌نیازها ≥ ۶۵ باشند ریشه همان مبحث است، وگرنه ضعیف‌ترین پیش‌نیاز را
    بازگشتی دنبال می‌کنیم (تا بالای زنجیره)."""
    students = await _class_students(db, class_id)
    student_ids = [s.user_id for s in students]
    states = await _states_for_students(db, student_ids)
    by_topic: dict[int, list[StudentTopicState]] = {}
    for st in states:
        by_topic.setdefault(st.topic_id, []).append(st)

    prereq_links = (await db.execute(select(Prerequisite))).scalars().all()
    prereqs_of: dict[int, list[int]] = {}
    for p in prereq_links:
        prereqs_of.setdefault(p.topic_id, []).append(p.prereq_topic_id)

    def mean_of(tid: int) -> float | None:
        rows = by_topic.get(tid, [])
        if not rows:
            return None
        return round(sum(r.effective_mastery for r in rows) / len(rows), 1)

    topic = await db.get(Topic, topic_id)
    chain: list[dict] = []
    current = topic
    seen: set[int] = set()
    root_reason = "topic"
    while current is not None and current.id not in seen:
        seen.add(current.id)
        m = mean_of(current.id)
        chain.append({"topic_id": current.id, "title": current.title_fa, "mastery": m})
        prereq_ids = prereqs_of.get(current.id, [])
        if not prereq_ids:
            root_reason = "topic"
            break
        prereq_masteries = [(pid, mean_of(pid)) for pid in prereq_ids]
        known = [m for _, m in prereq_masteries if m is not None]
        decision = root_cause_decision(known)
        if decision == "topic":
            root_reason = "topic"
            break
        # ضعیف‌ترین پیش‌نیازِ دارای داده را دنبال کن
        candidates = [(pid, m) for pid, m in prereq_masteries if m is not None]
        if not candidates:
            root_reason = "topic"
            break
        idx = weakest_prereq_index([m for _, m in candidates])
        next_topic = await db.get(Topic, candidates[idx][0])
        current = next_topic
        root_reason = "prerequisite"

    root = chain[-1]
    if root_reason == "topic":
        diagnosis = "مشکل در خودِ همین مبحث است؛ پیشنهاد: تدریس مجدد همین مبحث."
    else:
        diagnosis = f"مشکل اصلی احتمالاً از پیش‌نیاز «{root['title']}» است؛ پیشنهاد: مرور پیش‌نیاز قبل از ادامه."
    return {
        "topic": {"topic_id": topic.id, "title": topic.title_fa, "mastery": mean_of(topic.id)},
        "chain": chain,
        "root": root,
        "root_reason": root_reason,
        "diagnosis": diagnosis,
    }


async def need_groups(db: AsyncSession, class_id: int) -> dict:
    """گروه‌بندی هوشمند: هر دانش‌آموز در یکی از ۵ نوع نیاز (§6) — دو دانش‌آموز
    با نمره یکسان می‌توانند نیاز متفاوت داشته باشند."""
    settings = get_settings()
    students = await _class_students(db, class_id)
    student_ids = [s.user_id for s in students]
    states = await _states_for_students(db, student_ids)
    by_student: dict[int, list[StudentTopicState]] = {}
    for st in states:
        by_student.setdefault(st.student_user_id, []).append(st)

    topics = {t.id: t for t in (await db.execute(select(Topic))).scalars()}
    errors = (
        await db.execute(
            select(ErrorRecord).where(
                ErrorRecord.student_user_id.in_(student_ids),
                ErrorRecord.status.in_(["open", "in_remediation", "relapsed"]),
            )
        )
    ).scalars().all() if student_ids else []
    repeats_by_student: dict[int, int] = {}
    for e in errors:
        repeats_by_student[e.student_user_id] = repeats_by_student.get(e.student_user_id, 0) + 1

    tasks = (
        await db.execute(select(PlanTask).where(PlanTask.student_user_id.in_(student_ids)))
    ).scalars().all() if student_ids else []
    tasks_by_student: dict[int, list[PlanTask]] = {}
    for t in tasks:
        tasks_by_student.setdefault(t.student_user_id, []).append(t)

    # prereq weakness: any topic with weak prereq where student is below threshold
    prereq_links = (await db.execute(select(Prerequisite))).scalars().all()
    prereqs_of: dict[int, list[int]] = {}
    for p in prereq_links:
        prereqs_of.setdefault(p.topic_id, []).append(p.prereq_topic_id)

    users = {u.id: u for u in (await db.execute(select(User).where(User.id.in_(student_ids)))).scalars()} if student_ids else {}

    groups: dict[str, list[dict]] = {k: [] for k in NEED_FA}
    for s in students:
        sts = by_student.get(s.user_id, [])
        num = 0.0
        den = 0.0
        for st in sts:
            t = topics.get(st.topic_id)
            w = (t.blueprint_weight if t else 1.0) or 1.0
            num += w * st.effective_mastery
            den += w
        avg_e = round(num / den, 1) if den else 0.0
        avg_r = round(sum(st.retention for st in sts) / len(sts), 3) if sts else 0.0

        my_tasks = tasks_by_student.get(s.user_id, [])
        progress = (
            round(100.0 * sum(1 for t in my_tasks if t.status == "done") / len(my_tasks), 1)
            if my_tasks
            else None
        )

        # ریسک آینده: پیش‌نیاز ضعیف برای مبحثی که خود دانش‌آموز ضعیف است
        prereq_weak = False
        own = {st.topic_id: st for st in sts}
        for tid, st in own.items():
            if st.effective_mastery >= settings.threshold_consolidating:
                continue
            for pid in prereqs_of.get(tid, []):
                pst = own.get(pid)
                if pst is not None and pst.effective_mastery < settings.prerequisite_mastery_threshold:
                    prereq_weak = True

        need = classify_need(
            e=avg_e,
            r=avg_r,
            progress_pct=progress,
            repeat_count=repeats_by_student.get(s.user_id, 0),
            prereq_weak=prereq_weak,
        )
        groups[need].append(
            {
                "student_id": s.user_id,
                "full_name": users[s.user_id].full_name if s.user_id in users else f"#{s.user_id}",
                "mastery": avg_e,
                "retention": avg_r,
                "progress_pct": progress,
                "repeat_errors": repeats_by_student.get(s.user_id, 0),
                "prereq_weak": prereq_weak,
            }
        )

    return {
        "class_id": class_id,
        "groups": [
            {
                "need": k,
                "label": NEED_FA[k],
                "action": NEED_ACTION_FA[k],
                "students": groups[k],
            }
            for k in NEED_FA
        ],
    }
