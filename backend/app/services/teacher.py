"""Teacher panel services (سند پنل معلم §3, §4, §6):
- رادار مباحث کلاس: تجمیع همان رکوردهای SLM در سطح کلاس (بدون لایه داده جدید)
- ریشه‌یابی: پیمایش گراف پیش‌نیاز تا رسیدن به ریشه ضعف
- گروه‌بندی پنج‌گانه نیاز بر اساس دسته‌بندی §6"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.assessment import Exam, ExamAttempt
from app.models.catalog import Prerequisite, Topic
from app.models.org import ClassRoom, ClassTeacherAssignment, School, StudentProfile, User
from app.models.panel_extensions import ClassMission, TeacherParentReport
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


async def home_dashboard(db: AsyncSession, teacher_user_id: int) -> dict:
    """«خانهٔ معلم» (سند معلم §2): به چهار سؤال جواب می‌دهد —
    ۱) امروز چه کاری می‌توانم انجام دهم؟ (کارهای پیشنهادی امروز)
    ۲) چه چیزی نیازمند توجه است؟ (هشدارهای 🔴🟠🟡 با دکمه اقدام)
    ۳) KPIهای کلان: میانگین تسط مؤثر، پیشرفت برنامه، میانگین آزمون دوره
    ۴) مقایسه در «حد و پیوستگی» — همه از همان هسته SLM، بدون لایه داده جدید."""
    links = (
        await db.execute(
            select(ClassTeacherAssignment).where(
                ClassTeacherAssignment.teacher_user_id == teacher_user_id,
                ClassTeacherAssignment.status == "active",
            )
        )
    ).scalars().all()
    class_ids = [l.class_id for l in links]
    if not class_ids:
        return {"classes": 0, "kpis": None, "alerts": [], "tasks": [], "note_fa": "کلاسی به شما تخصیص نیافته است."}

    classes = (await db.execute(select(ClassRoom).where(ClassRoom.id.in_(class_ids)))).scalars().all()
    class_by_id = {c.id: c for c in classes}
    subject_by_class = {l.class_id: l.subject for l in links}

    all_student_ids: list[int] = []
    for cid in class_ids:
        all_student_ids.extend([s.user_id for s in await _class_students(db, cid)])
    all_student_ids = sorted(set(all_student_ids))

    states = await _states_for_students(db, all_student_ids)
    settings = get_settings()

    # ---------- KPI ۱: میانگین تسط مؤثر کل کلاس‌ها ----------
    with_data = [st.effective_mastery for st in states if st.evidence_count >= settings.evidence_min_for_status]
    avg_mastery = round(sum(with_data) / len(with_data), 1) if with_data else None

    # ---------- KPI ۲: پیشرفت برنامه (٪ کارهای done از کل کارها) ----------
    tasks = (
        await db.execute(select(PlanTask).where(PlanTask.student_user_id.in_(all_student_ids)))
    ).scalars().all() if all_student_ids else []
    plan_pct = round(100.0 * sum(1 for t in tasks if t.status == "done") / len(tasks), 1) if tasks else None

    # ---------- KPI ۳: میانگین نمرهٔ آزمون‌های دوره‌ای تصحیح‌شده ----------
    attempts = (
        await db.execute(
            select(ExamAttempt.percent)
            .join(Exam, Exam.id == ExamAttempt.exam_id)
            .where(
                ExamAttempt.student_user_id.in_(all_student_ids),
                ExamAttempt.status == "graded",
                Exam.exam_type == "period_exam",
                ExamAttempt.percent.is_not(None),
            )
        )
    ).scalars().all() if all_student_ids else []
    exam_pct = round(sum(attempts) / len(attempts), 1) if attempts else None

    # ---------- هشدارها + کارهای پیشنهادی امروز (از رادار هر کلاس) ----------
    alerts: list[dict] = []
    today_tasks: list[dict] = []
    weak_topic_titles: set[str] = set()
    prereq_flagged: set[str] = set()

    for cid in class_ids:
        radar = await class_radar(db, cid)
        cls = class_by_id.get(cid)
        class_name = cls.name if cls else f"کلاس {cid}"
        subject = subject_by_class.get(cid)

        for row in radar["rows"]:
            # 🔴 مبحث بحرانی/ضعیف با اکثریت نیازمند توجه
            if row["status"] in ("critical", "weak") and row["weak_count"] > 0:
                ratio = row["weak_count"] / row["students_with_data"] if row["students_with_data"] else 0
                if ratio >= 0.5:
                    alerts.append(
                        {
                            "severity": "high",
                            "class_id": cid,
                            "class_name": class_name,
                            "topic_id": row["topic_id"],
                            "title_fa": f"«{row['title']}» در {class_name} نیازمند آموزش مجدد",
                            "evidence_fa": f"{row['weak_count']} از {row['students_with_data']} دانش‌آموز زیر آستانه تثبیت",
                            "action_fa": "ساخت بسته ترمیمی برای گروه",
                            "action_view": "class",
                        }
                    )
                    weak_topic_titles.add(row["title"])
                    today_tasks.append(
                        {
                            "title": f"آموزش مجدد «{row['title']}» — {class_name}",
                            "detail": f"{row['weak_count']} دانش‌آموز نیازمند؛ پیشنهاد: بسته ترمیمی گروهی",
                            "priority": "high",
                            "class_id": cid,
                            "topic_id": row["topic_id"],
                        }
                    )

            # 🟠 ضعف پیش‌نیاز → ریشه‌یابی
            if row["prereq_weak"]:
                prereq_flagged.add(row["title"])
                alerts.append(
                    {
                        "severity": "medium",
                        "class_id": cid,
                        "class_name": class_name,
                        "topic_id": row["topic_id"],
                        "title_fa": f"پیش‌نیاز «{row['title']}» ضعیف است",
                        "evidence_fa": "یکی از پیش‌نیازهای این مبحث زیر آستانه است؛ ریشه‌یابی کنید",
                        "action_fa": "ریشه‌یابی با گراف پیش‌نیاز",
                        "action_view": "class",
                    }
                )
                today_tasks.append(
                    {
                        "title": f"ریشه‌یابی «{row['title']}» — {class_name}",
                        "detail": "بررسی زنجیره پیش‌نیاز پیش از ادامه تدریس",
                        "priority": "medium",
                        "class_id": cid,
                        "topic_id": row["topic_id"],
                    }
                )

            # 🟡 افت ماندگاری (R پایین با وجود تسط قابل قبول)
            if (
                row["status"] in ("mastered", "consolidating")
                and row["avg_retention"] < settings.threshold_consolidating / 100
                and row["students_with_data"] >= settings.evidence_min_for_status
            ):
                alerts.append(
                    {
                        "severity": "low",
                        "class_id": cid,
                        "class_name": class_name,
                        "topic_id": row["topic_id"],
                        "title_fa": f"ماندگاری «{row['title']}» رو به افت است",
                        "evidence_fa": f"میانگین ماندگاری {round(row['avg_retention'] * 100)}٪ با وجود تسط {round(row['avg_mastery'])}٪",
                        "action_fa": "مرور فاصله‌دار برنامه‌ریزی کنید",
                        "action_view": "class",
                    }
                )

    # ---------- پیشنهاد ساخت آزمون (§8.5) ----------
    if weak_topic_titles:
        top_topic = sorted(weak_topic_titles)[0]
        today_tasks.append(
            {
                "title": f"ساخت آزمون برای رفع ضعف «{top_topic}»",
                "detail": "بر اساس آمار خطاهای باز این هفته — از سازنده آزمون بسازید",
                "priority": "medium",
                "class_id": None,
                "topic_id": None,
                "view": "builder",
            }
        )

    order = {"high": 0, "medium": 1, "low": 2}
    alerts.sort(key=lambda a: order.get(a["severity"], 3))
    today_tasks.sort(key=lambda t: order.get(t["priority"], 3))

    return {
        "classes": len(class_ids),
        "kpis": {
            "avg_mastery": avg_mastery,
            "plan_progress_pct": plan_pct,
            "exam_pct": exam_pct,
            "weak_topics": len(weak_topic_titles),
            "prereq_flagged": len(prereq_flagged),
        },
        "alerts": alerts,
        "tasks": today_tasks[:8],
        "note_fa": "هشدارها برای «بررسی» هستند، نه ارزیابی قطعی. هر کارت دکمه اقدام دارد.",
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


# ==============================================================================
# §5 دانش‌آموزان: «چرا؟» و خط زمان (توضیح یک‌کلیکی + مسیر یادگیری)
# ==============================================================================

CAUSE_FA: dict[str, str] = {
    "conceptual": "ضعف مفهومی",
    "prerequisite": "ضعف پیش‌نیاز",
    "calculation": "خطای محاسباتی",
    "careless": "بی‌دقتی",
    "time_management": "کمبود زمان",
    "guess": "حدس",
}

SOURCE_FA: dict[str, str] = {
    "exam": "آزمون",
    "period_exam": "آزمون دوره‌ای",
    "cumulative": "آزمون تجمعی",
    "quiz": "آزمونک",
    "practice": "تمرین",
    "retest": "بازآزمون",
    "remediation": "بسته ترمیمی",
    "ai_chat": "گفت‌وگوی آموزشی",
    "self_report": "خوداظهاری",
    "tutoring": "تدریس خصوصی",
}

ERROR_STATUS_FA = {
    "open": "باز",
    "in_remediation": "در حال ترمیم",
    "relapsed": "بازگشته",
    "resolved": "رفع‌شده",
}

TASK_STATUS_FA = {"pending": "در انتظار", "done": "انجام‌شده", "missed": "جامانده", "moved": "جابه‌جا‌شده"}


async def _profile_in_class(db: AsyncSession, class_id: int, student_id: int) -> StudentProfile:
    """دانش‌آموز باید عضو همین کلاس باشد (§18 دامنهٔ محدود معلم)."""
    profile = (
        await db.execute(
            select(StudentProfile).where(
                StudentProfile.class_id == class_id,
                StudentProfile.user_id == student_id,
            )
        )
    ).scalar_one_or_none()
    if profile is None:
        raise LookupError("این دانش‌آموز در این کلاس ثبت نشده است")
    return profile


async def _prereq_map(db: AsyncSession) -> dict[int, list[int]]:
    prereqs_of: dict[int, list[int]] = {}
    for p in (await db.execute(select(Prerequisite))).scalars().all():
        prereqs_of.setdefault(p.topic_id, []).append(p.prereq_topic_id)
    return prereqs_of


async def student_metrics(db: AsyncSession, student_ids: list[int]) -> dict[int, dict]:
    """متریک پایهٔ هر دانش‌آموز — مبنای کارت «چرا؟»، خط زمان و گروه‌بندی A–D.
    همه از همان هستهٔ SLM (بدون لایهٔ دادهٔ جدید) خوانده می‌شود."""
    settings = get_settings()
    out: dict[int, dict] = {
        sid: {
            "mastery": 0.0,
            "retention": 0.0,
            "progress_pct": None,
            "open_errors": 0,
            "error_causes": {},
            "all_error_causes": {},
            "prereq_weak": False,
            "evidence_count": 0,
            "last_evidence_at": None,
            "weakest_topic": None,
            "tasks_total": 0,
            "tasks_done": 0,
        }
        for sid in student_ids
    }
    if not student_ids:
        return out

    states = await _states_for_students(db, student_ids)
    topics = {t.id: t for t in (await db.execute(select(Topic))).scalars()}
    prereqs_of = await _prereq_map(db)

    errors = (
        (await db.execute(select(ErrorRecord).where(ErrorRecord.student_user_id.in_(student_ids)))).scalars().all()
    )
    tasks = (await db.execute(select(PlanTask).where(PlanTask.student_user_id.in_(student_ids)))).scalars().all()

    by_state: dict[int, list[StudentTopicState]] = {}
    for st in states:
        by_state.setdefault(st.student_user_id, []).append(st)
    by_error: dict[int, list[ErrorRecord]] = {}
    for e in errors:
        by_error.setdefault(e.student_user_id, []).append(e)
    by_task: dict[int, list[PlanTask]] = {}
    for t in tasks:
        by_task.setdefault(t.student_user_id, []).append(t)

    for sid, row in out.items():
        sts = by_state.get(sid, [])
        num = 0.0
        den = 0.0
        for st in sts:
            t = topics.get(st.topic_id)
            w = (t.blueprint_weight if t else 1.0) or 1.0
            num += w * st.effective_mastery
            den += w
        row["mastery"] = round(num / den, 1) if den else 0.0
        row["retention"] = round(sum(st.retention for st in sts) / len(sts), 3) if sts else 0.0
        row["evidence_count"] = sum(st.evidence_count for st in sts)
        row["last_evidence_at"] = max(
            (st.last_evidence_at for st in sts if st.last_evidence_at), default=None
        )

        mine = by_task.get(sid, [])
        row["tasks_total"] = len(mine)
        row["tasks_done"] = sum(1 for t in mine if t.status == "done")
        row["progress_pct"] = round(100.0 * row["tasks_done"] / len(mine), 1) if mine else None

        errs = by_error.get(sid, [])
        open_errs = [e for e in errs if e.status in ("open", "in_remediation", "relapsed")]
        row["open_errors"] = len(open_errs)
        row["error_causes"] = dict(Counter(e.cause for e in open_errs))
        row["all_error_causes"] = dict(Counter(e.cause for e in errs))

        # ریسک آینده: پیش‌نیازِ زیر آستانه برای مبحثی که خود دانش‌آموز ضعیف است
        own = {st.topic_id: st for st in sts}
        for tid, st in own.items():
            if st.effective_mastery >= settings.threshold_consolidating:
                continue
            for pid in prereqs_of.get(tid, []):
                pst = own.get(pid)
                if pst is not None and pst.effective_mastery < settings.prerequisite_mastery_threshold:
                    row["prereq_weak"] = True

        if sts:
            weak = min(sts, key=lambda s: s.effective_mastery)
            wt = topics.get(weak.topic_id)
            row["weakest_topic"] = {
                "topic_id": weak.topic_id,
                "title": wt.title_fa if wt else f"#{weak.topic_id}",
                "mastery": weak.effective_mastery,
                "retention": weak.retention,
            }
    return out


async def _problem_prereq(db: AsyncSession, student_id: int) -> str | None:
    """ضعیف‌ترین پیش‌نیازِ زیر آستانه که روی یادگیری این دانش‌آموز اثر گذاشته است."""
    settings = get_settings()
    states = await _states_for_students(db, [student_id])
    if not states:
        return None
    topics = {t.id: t for t in (await db.execute(select(Topic))).scalars()}
    prereqs_of = await _prereq_map(db)
    own = {st.topic_id: st for st in states}
    worst: tuple[float, str] | None = None
    for tid, st in own.items():
        if st.effective_mastery >= settings.threshold_consolidating:
            continue
        for pid in prereqs_of.get(tid, []):
            pst = own.get(pid)
            if pst is None or pst.effective_mastery >= settings.prerequisite_mastery_threshold:
                continue
            title = topics[pid].title_fa if pid in topics else f"#{pid}"
            if worst is None or pst.effective_mastery < worst[0]:
                worst = (pst.effective_mastery, title)
    return worst[1] if worst else None


async def student_why(db: AsyncSession, class_id: int, student_id: int) -> dict:
    """§5.2 کارت «چرا؟»: چرا این دانش‌آموز در این گروه نیاز است — با شواهد عددی،
    آخرین شکست/موفقیت و پیشنهاد اقدام (اجرا فقط با تأیید معلم)."""
    await _profile_in_class(db, class_id, student_id)
    settings = get_settings()
    m = (await student_metrics(db, [student_id]))[student_id]
    need = classify_need(
        e=m["mastery"],
        r=m["retention"],
        progress_pct=m["progress_pct"],
        repeat_count=m["open_errors"],
        prereq_weak=m["prereq_weak"],
    )

    reasons: list[str] = []
    if m["evidence_count"] == 0:
        reasons.append("هنوز شواهد کافی برای این دانش‌آموز ثبت نشده است")
    else:
        below = m["mastery"] < settings.threshold_consolidating
        reasons.append(
            f"میانگین تسط مؤثر {round(m['mastery'])}٪ — "
            f"{'زیر' if below else 'بالای'} آستانهٔ تثبیت {settings.threshold_consolidating}٪"
        )
        if m["last_evidence_at"] is not None:
            days = max(0, (datetime.utcnow() - m["last_evidence_at"]).days)
            reasons.append(f"ماندگاری {round(m['retention'] * 100)}٪ — آخرین شاهد {days} روز پیش")
        else:
            reasons.append(f"ماندگاری {round(m['retention'] * 100)}٪ — تاریخچهٔ شواهد ندارد")

    dominant = None
    if m["error_causes"]:
        dominant = max(m["error_causes"].items(), key=lambda kv: kv[1])[0]
        reasons.append(
            f"{m['open_errors']} خطای باز/بازگشته — غالب: "
            f"«{CAUSE_FA.get(dominant, dominant)}» با {m['error_causes'][dominant]} مورد"
        )
    elif m["open_errors"]:
        reasons.append(f"{m['open_errors']} خطای باز ثبت شده است")

    problem_prereq = await _problem_prereq(db, student_id)
    if problem_prereq:
        reasons.append(
            f"پیش‌نیاز «{problem_prereq}» زیر آستانهٔ {settings.prerequisite_mastery_threshold}٪ است"
        )
    if m["progress_pct"] is not None:
        reasons.append(f"پیشرفت برنامه {round(m['progress_pct'])}٪ ({m['tasks_done']} از {m['tasks_total']} کار)")

    # آخرین شکست و آخرین تلاش موفق
    errors = list(
        (
            await db.execute(
                select(ErrorRecord)
                .where(ErrorRecord.student_user_id == student_id)
                .order_by(ErrorRecord.created_at.desc())
            )
        ).scalars()
    )
    last_failure = None
    if errors:
        e0 = errors[0]
        t0 = await db.get(Topic, e0.topic_id)
        last_failure = {
            "at": e0.created_at.isoformat() if e0.created_at else None,
            "days_ago": max(0, (datetime.utcnow() - e0.created_at).days) if e0.created_at else None,
            "topic": t0.title_fa if t0 else None,
            "cause": e0.cause,
            "cause_fa": CAUSE_FA.get(e0.cause, e0.cause),
            "status": e0.status,
            "status_fa": ERROR_STATUS_FA.get(e0.status, e0.status),
        }

    evidences = list(
        (
            await db.execute(
                select(Evidence)
                .where(Evidence.student_user_id == student_id)
                .order_by(Evidence.occurred_at.desc())
            )
        ).scalars()
    )
    success_ev = next((ev for ev in evidences if ev.partial_credit >= 0.75), None)
    last_success = None
    if success_ev is not None:
        t1 = await db.get(Topic, success_ev.topic_id)
        last_success = {
            "at": success_ev.occurred_at.isoformat() if success_ev.occurred_at else None,
            "topic": t1.title_fa if t1 else None,
            "source": success_ev.source,
            "source_fa": SOURCE_FA.get(success_ev.source, success_ev.source),
        }

    weakest = m["weakest_topic"]
    suggestion = NEED_ACTION_FA[need]
    if weakest:
        suggestion = f"{suggestion} — با تمرکز روی مبحث «{weakest['title']}»"

    return {
        "class_id": class_id,
        "student_id": student_id,
        "need": need,
        "need_label": NEED_FA[need],
        "action": NEED_ACTION_FA[need],
        "mastery": m["mastery"],
        "retention": m["retention"],
        "progress_pct": m["progress_pct"],
        "open_errors": m["open_errors"],
        "reasons_fa": reasons,
        "dominant_cause": dominant,
        "dominant_cause_fa": CAUSE_FA.get(dominant, dominant) if dominant else None,
        "problem_prereq": problem_prereq,
        "last_failure": last_failure,
        "last_success": last_success,
        "similar_errors_fa": {
            CAUSE_FA.get(c, c): n for c, n in sorted(m["error_causes"].items(), key=lambda kv: -kv[1])
        },
        "suggestion_fa": suggestion,
        "note_fa": "این توضیح از شواهد ثبت‌شدهٔ خود دانش‌آموز ساخته می‌شود؛ هیچ پیشنهادی بدون تأیید شما اجرا نمی‌شود.",
    }


async def student_timeline(db: AsyncSession, class_id: int, student_id: int, limit: int = 40) -> dict:
    """§5.3 خط زمان دانش‌آموز: رویدادهای یادگیری به ترتیب زمان — خطا، شاهد،
    آزمون، برنامه و تغییر وضعیت مبحث («ضعیف ← بهبود ← افت دوباره»)."""
    await _profile_in_class(db, class_id, student_id)
    events: list[dict] = []

    def _iso(dt) -> str | None:
        return dt.isoformat() if dt else None

    topics = {t.id: t for t in (await db.execute(select(Topic))).scalars()}

    def _topic_title(tid: int | None) -> str:
        if tid is None:
            return "—"
        return topics[tid].title_fa if tid in topics else f"#{tid}"

    errors = list(
        (
            await db.execute(
                select(ErrorRecord)
                .where(ErrorRecord.student_user_id == student_id)
                .order_by(ErrorRecord.created_at.desc())
                .limit(15)
            )
        ).scalars()
    )
    for e in errors:
        resolved = e.status == "resolved"
        events.append(
            {
                "at": _iso(e.created_at),
                "kind": "error",
                "tone": "success" if resolved else "danger",
                "title_fa": f"خطا در «{_topic_title(e.topic_id)}»",
                "detail_fa": f"{CAUSE_FA.get(e.cause, e.cause)} — وضعیت: {ERROR_STATUS_FA.get(e.status, e.status)}",
            }
        )

    evidences = list(
        (
            await db.execute(
                select(Evidence)
                .where(Evidence.student_user_id == student_id)
                .order_by(Evidence.occurred_at.desc())
                .limit(15)
            )
        ).scalars()
    )
    for ev in evidences:
        ok = ev.partial_credit >= 0.75
        events.append(
            {
                "at": _iso(ev.occurred_at),
                "kind": "evidence",
                "tone": "success" if ok else "warning",
                "title_fa": f"{SOURCE_FA.get(ev.source, ev.source)} در «{_topic_title(ev.topic_id)}»",
                "detail_fa": "پاسخ درست/تسلط کافی" if ok else "نیازمند مرور بعدی",
            }
        )

    attempts = list(
        (
            await db.execute(
                select(ExamAttempt, Exam)
                .join(Exam, Exam.id == ExamAttempt.exam_id)
                .where(ExamAttempt.student_user_id == student_id)
                .order_by(ExamAttempt.id.desc())
                .limit(10)
            )
        ).all()
    )
    for attempt, exam in attempts:
        events.append(
            {
                "at": _iso(attempt.submitted_at or attempt.started_at),
                "kind": "exam",
                "tone": "success" if (attempt.percent or 0) >= 70 else "danger",
                "title_fa": f"آزمون «{exam.title_fa}»",
                "detail_fa": (
                    f"{round(attempt.percent)}٪ — {SOURCE_FA.get(exam.exam_type, exam.exam_type)}"
                    if attempt.percent is not None
                    else "در حال شرکت"
                ),
            }
        )

    tasks = list(
        (
            await db.execute(
                select(PlanTask)
                .where(PlanTask.student_user_id == student_id)
                .order_by(PlanTask.id.desc())
                .limit(10)
            )
        ).scalars()
    )
    for t in tasks:
        events.append(
            {
                "at": _iso(t.created_at),
                "kind": "plan",
                "tone": "success" if t.status == "done" else ("danger" if t.status == "missed" else "neutral"),
                "title_fa": f"برنامهٔ {SOURCE_FA.get(t.task_type, t.task_type)} — «{_topic_title(t.topic_id)}»",
                "detail_fa": f"وضعیت: {TASK_STATUS_FA.get(t.status, t.status)}",
            }
        )

    for st in (
        await db.execute(select(StudentTopicState).where(StudentTopicState.student_user_id == student_id))
    ).scalars():
        for h in (st.history or [])[:12]:
            at = h.get("at")
            if isinstance(at, str):
                at = at.replace("Z", "")
            e_val = h.get("e", h.get("E"))
            events.append(
                {
                    "at": at,
                    "kind": "state",
                    "tone": "neutral",
                    "title_fa": f"به‌روزرسانی تسط «{_topic_title(st.topic_id)}»",
                    "detail_fa": (
                        f"منبع: {SOURCE_FA.get(h.get('source', ''), h.get('source') or '—')} — "
                        f"تسط مؤثر {round(float(e_val))}٪" if e_val is not None else "تغییر وضعیت مبحث"
                    ),
                }
            )

    events.sort(key=lambda e: e["at"] or "", reverse=True)
    return {
        "class_id": class_id,
        "student_id": student_id,
        "events": events[:limit],
        "note_fa": "خط زمان از شواهد، خطاها، آزمون‌ها و برنامهٔ همین دانش‌آموز ساخته می‌شود — نه فقط یک نمره.",
    }


# ==============================================================================
# §7 گروه‌بندی A–D (آموزش افتراقی) — کنارِ گروه‌بندی پنج‌گانهٔ نیاز (§6)
# ==============================================================================

ABCD_META: dict[str, dict[str, str]] = {
    "A": {
        "label": "نیازمند آموزش مجدد",
        "problem_fa": "مفهوم پایه مشکل دارد",
        "action_fa": "ساخت بستهٔ آموزشی برای گروه",
    },
    "B": {
        "label": "نیازمند تمرین",
        "problem_fa": "مفهوم را می‌داند، خطای محاسباتی دارد",
        "action_fa": "ارسال تمرین محاسباتی",
    },
    "C": {
        "label": "مشکل زمان",
        "problem_fa": "دقت خوب، زمان پاسخ بالا",
        "action_fa": "ارسال تمرین زمان‌دار",
    },
    "D": {
        "label": "مسلط",
        "problem_fa": "آمادهٔ تمرین پیشرفته",
        "action_fa": "ارسال تمرین پیشرفته",
    },
}


def abcd_of(metrics_row: dict, threshold: float) -> tuple[str, str]:
    """§7.1 «دو دانش‌آموز با نمرهٔ یکسان، نیاز یکسان نیست»: گروه از روی نوع
    خطا (نه فقط نمره) انتخاب می‌شود؛ بدون خطا، تسط و ماندگاری تعیین‌کننده است."""
    causes = metrics_row.get("error_causes") or {}
    if causes:
        score = {
            "A": causes.get("conceptual", 0) + causes.get("prerequisite", 0),
            "B": causes.get("calculation", 0) + causes.get("careless", 0),
            "C": causes.get("time_management", 0) + causes.get("guess", 0),
        }
        best = max(("A", "B", "C"), key=lambda k: score[k])  # در تساوی: A، سپس B، سپس C
        if score[best] > 0:
            cause_name = {
                "A": "مفهومی/پیش‌نیاز",
                "B": "محاسباتی/بی‌دقتی",
                "C": "زمان/حدس",
            }[best]
            return best, f" غالب‌ترین خطای باز از نوع {cause_name} است ({score[best]} مورد)"
    if metrics_row["mastery"] < threshold:
        return "A", f"تسط {round(metrics_row['mastery'])}٪ زیر آستانهٔ تثبیت است"
    if metrics_row["retention"] < 0.6:
        return "D", "مسلط است اما ماندگاری رو به افت است — پایش مرور فاصله‌دار"
    return "D", "تسط و ماندگاری بالا — آمادهٔ کار پیشرفته"


async def abcd_groups(db: AsyncSession, class_id: int) -> dict:
    """گروه‌بندی خودکار کلاس به ۴ گروه A تا D (§7، شکل ۸) با دلیل فارسی هر دانش‌آموز."""
    settings = get_settings()
    students = await _class_students(db, class_id)
    ids = [s.user_id for s in students]
    metrics = await student_metrics(db, ids)
    users = (
        {u.id: u for u in (await db.execute(select(User).where(User.id.in_(ids)))).scalars()}
        if ids
        else {}
    )

    buckets: dict[str, list[dict]] = {k: [] for k in ABCD_META}
    for s in students:
        m = metrics[s.user_id]
        key, why = abcd_of(m, settings.threshold_consolidating)
        buckets[key].append(
            {
                "student_id": s.user_id,
                "full_name": users[s.user_id].full_name if s.user_id in users else f"#{s.user_id}",
                "mastery": m["mastery"],
                "retention": m["retention"],
                "progress_pct": m["progress_pct"],
                "repeat_errors": m["open_errors"],
                "why_fa": why.strip(),
            }
        )

    return {
        "class_id": class_id,
        "scheme": "abcd",
        "note_fa": "گروه‌بندی از روی «نوع نیاز» است، نه رتبهٔ نمره — ارسال یک تمرین واحد برای همه، وقت همه را تلف می‌کند.",
        "groups": [
            {
                "key": k,
                "label": ABCD_META[k]["label"],
                "problem": ABCD_META[k]["problem_fa"],
                "action": ABCD_META[k]["action_fa"],
                "count": len(buckets[k]),
                "students": buckets[k],
            }
            for k in ABCD_META
        ],
    }


# ==============================================================================
# §9 مأموریت کلاسی — هدف معلم ← اجرای سیستم ← سنجش
# ==============================================================================


async def _class_topic_mastery(db: AsyncSession, class_id: int, topic_id: int | None) -> dict[int, float]:
    """تسط مؤثر هر دانش‌آموز روی مبحث هدف (یا میانگین کل، وقتی topic_id خالی است)."""
    students = await _class_students(db, class_id)
    ids = [s.user_id for s in students]
    if not ids:
        return {}
    if topic_id is not None:
        rows = (
            await db.execute(
                select(StudentTopicState).where(
                    StudentTopicState.student_user_id.in_(ids),
                    StudentTopicState.topic_id == topic_id,
                )
            )
        ).scalars().all()
        return {r.student_user_id: r.effective_mastery for r in rows}
    metrics = await student_metrics(db, ids)
    return {sid: row["mastery"] for sid, row in metrics.items()}


async def mission_row(db: AsyncSession, mission: ClassMission) -> dict:
    """ردیف مأموریت + پیشرفت زنده (همان سنجشِ مرحلهٔ سوم الگوی §9)."""
    per_student = await _class_topic_mastery(db, mission.class_id, mission.topic_id)
    values = list(per_student.values())
    current = round(sum(values) / len(values), 1) if values else None
    targets: list[int] = list(mission.target_students or [])
    achieved = sum(1 for sid in targets if per_student.get(sid, 0) >= mission.target_mastery)
    if current is not None and mission.target_mastery:
        progress = max(0.0, min(100.0, round(100.0 * current / mission.target_mastery, 1)))
    else:
        progress = 0.0
    topic = await db.get(Topic, mission.topic_id) if mission.topic_id else None
    cls = await db.get(ClassRoom, mission.class_id)
    return {
        "id": mission.id,
        "class_id": mission.class_id,
        "class_name": cls.name if cls else None,
        "topic_id": mission.topic_id,
        "topic_title": topic.title_fa if topic else None,
        "title_fa": mission.title_fa,
        "target_mastery": mission.target_mastery,
        "deadline": mission.deadline.isoformat() if mission.deadline else None,
        "status": mission.status,
        "status_fa": {"active": "در حال اجرا", "completed": "تکمیل‌شده", "archived": "بایگانی"}.get(
            mission.status, mission.status
        ),
        "baseline_mastery": mission.baseline_mastery,
        "current_mastery": current,
        "progress_pct": progress,
        "students_total": len(targets),
        "students_achieved": achieved,
        "result_note_fa": mission.result_note_fa,
        "created_at": mission.created_at.isoformat() if mission.created_at else None,
        "completed_at": mission.completed_at.isoformat() if mission.completed_at else None,
        "note_fa": "پیشرفت از تسط مؤثر همین کلاس محاسبه می‌شود؛ هدف را معلم تعیین می‌کند.",
    }


async def create_mission(
    db: AsyncSession,
    class_id: int,
    *,
    title_fa: str,
    topic_id: int | None = None,
    target_mastery: float = 70.0,
    deadline=None,
    actor_user_id: int | None = None,
) -> dict:
    """§9 مرحلهٔ ۱: هدف معلم + یافتن دانش‌آموزان زیر آستانه (اجرای خودکار)."""
    per_student = await _class_topic_mastery(db, class_id, topic_id)
    values = list(per_student.values())
    baseline = round(sum(values) / len(values), 1) if values else None
    targets = sorted(sid for sid, v in per_student.items() if v < target_mastery)
    mission = ClassMission(
        class_id=class_id,
        topic_id=topic_id,
        title_fa=title_fa,
        target_mastery=target_mastery,
        deadline=deadline,
        status="active",
        baseline_mastery=baseline,
        target_students=targets,
        created_by=actor_user_id,
    )
    db.add(mission)
    await db.flush()
    return await mission_row(db, mission)


async def list_missions(db: AsyncSession, class_id: int) -> dict:
    rows = list(
        (
            await db.execute(
                select(ClassMission).where(ClassMission.class_id == class_id).order_by(ClassMission.id.desc())
            )
        ).scalars()
    )
    out = []
    for m in rows:
        out.append(await mission_row(db, m))
    return {"class_id": class_id, "missions": out}


async def complete_mission(db: AsyncSession, mission_id: int, note_fa: str | None = None) -> dict | None:
    """§9 مرحلهٔ ۳: سنجش نهایی و بستن مأموریت (با ثبت نتیجهٔ اندازه‌گیری‌شده)."""
    mission = await db.get(ClassMission, mission_id)
    if mission is None:
        return None
    row = await mission_row(db, mission)
    mission.status = "completed"
    mission.completed_at = datetime.utcnow()
    result = note_fa or (
        f"نتیجهٔ سنجش: تسط فعلی {row['current_mastery'] if row['current_mastery'] is not None else '—'}٪ "
        f"در برابر هدف {round(mission.target_mastery)}٪ — "
        f"{row['students_achieved']} از {row['students_total']} دانش‌آموز هدف را رسیده‌اند."
    )
    mission.result_note_fa = result
    await db.flush()
    row = await mission_row(db, mission)
    return row


# ==============================================================================
# §4 نمایهٔ مدیریتی معلم (دید خودِ معلم) — دوگانهٔ آموزشی/مدیریتی، بدون امتیاز کل
# ==============================================================================


async def management_profile(db: AsyncSession, teacher_user_id: int) -> dict:
    """§4.1 سند مدیر مدرسه، از زاویهٔ خودِ معلم: آمار آموزشی + رفتار آموزشی +
    پاسخ‌گویی + وضعیت صلاحیت — هرگز در یک امتیاز عددی ادغام نمی‌شوند."""
    from app.models.rbac import AuditLog
    from app.models.teacher_assessment import TeacherQualification
    from app.models.teacher_copilot import TeacherSuggestion

    links = list(
        (
            await db.execute(
                select(ClassTeacherAssignment).where(
                    ClassTeacherAssignment.teacher_user_id == teacher_user_id,
                    ClassTeacherAssignment.status == "active",
                )
            )
        ).scalars()
    )
    class_ids = [l.class_id for l in links]
    subjects = sorted({l.subject for l in links if l.subject})
    student_ids: list[int] = []
    for cid in class_ids:
        student_ids.extend([s.user_id for s in await _class_students(db, cid)])
    student_ids = sorted(set(student_ids))

    metrics = await student_metrics(db, student_ids)
    with_data = [m for m in metrics.values() if m["evidence_count"] > 0]
    avg_mastery = round(sum(m["mastery"] for m in with_data) / len(with_data), 1) if with_data else None
    avg_retention = (
        round(sum(m["retention"] for m in with_data) / len(with_data), 3) if with_data else None
    )

    # رشد: میانگین (E فعلی − نخستین ثبت تاریخچه) روی مباحث دارای ≥۲ ثبت
    states = await _states_for_students(db, student_ids) if student_ids else []
    deltas = [
        st.effective_mastery - float(st.history[0].get("e", st.history[0].get("E", st.effective_mastery)))
        for st in states
        if len(st.history or []) >= 2 and (st.history[0].get("e") is not None or st.history[0].get("E") is not None)
    ]
    growth = round(sum(deltas) / len(deltas), 1) if deltas else None

    tasks = (
        (await db.execute(select(PlanTask).where(PlanTask.student_user_id.in_(student_ids)))).scalars().all()
        if student_ids
        else []
    )
    plan_pct = round(100.0 * sum(1 for t in tasks if t.status == "done") / len(tasks), 1) if tasks else None
    retests = sum(1 for t in tasks if t.task_type in ("retest", "quiz"))

    graded = (
        (
            await db.execute(
                select(ExamAttempt.id).where(
                    ExamAttempt.student_user_id.in_(student_ids),
                    ExamAttempt.status == "graded",
                )
            )
        ).scalars().all()
        if student_ids
        else []
    )
    distinct_students_with_grade = len(set(graded))
    exam_participation = (
        round(100.0 * len(graded) / len(student_ids), 1) if student_ids else None
    )

    my_exams = list(
        (await db.execute(select(Exam).where(Exam.created_by == teacher_user_id))).scalars()
    )
    published = [e for e in my_exams if e.status in ("published", "closed", "graded")]

    suggestions = (
        (
            await db.execute(select(TeacherSuggestion).where(TeacherSuggestion.class_id.in_(class_ids)))
        ).scalars().all()
        if class_ids
        else []
    )
    sugg_counts = dict(Counter(s.status for s in suggestions))
    executed = sugg_counts.get("approved", 0) + sugg_counts.get("edited", 0)

    copilot_queries = (
        (
            await db.execute(
                select(AuditLog.id).where(
                    AuditLog.actor_user_id == teacher_user_id,
                    AuditLog.action == "teacher_copilot_query",
                )
            )
        ).scalars().all()
    )

    flagged = 0
    for m in metrics.values():
        if (
            classify_need(
                e=m["mastery"],
                r=m["retention"],
                progress_pct=m["progress_pct"],
                repeat_count=m["open_errors"],
                prereq_weak=m["prereq_weak"],
            )
            == "intervention"
        ):
            flagged += 1

    qualification_row = None
    qual = (
        await db.execute(
            select(TeacherQualification)
            .where(TeacherQualification.teacher_user_id == teacher_user_id)
            .order_by(TeacherQualification.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if qual is not None:
        from app.services import teacher_qualification as tq

        qualification_row = await tq._qual_row(db, qual)

    return {
        "teacher_id": teacher_user_id,
        "subjects": subjects,
        "classes_count": len(class_ids),
        "students_count": len(student_ids),
        "education": {
            "avg_mastery": avg_mastery,
            "avg_retention": avg_retention,
            "growth": growth,
            "plan_completion_pct": plan_pct,
            "exam_participation_pct": exam_participation,
            "graded_answers": distinct_students_with_grade,
        },
        "behavior": {
            "exams_created": len(my_exams),
            "exams_published": len(published),
            "suggestions_executed": executed,
            "suggestions_open": sugg_counts.get("proposed", 0),
            "students_flagged_for_intervention": flagged,
            "retests_scheduled": retests,
            "copilot_queries": len(copilot_queries),
        },
        "responsiveness": {
            "questions_received": None,
            "response_target_hours": 48,
            "note_fa": "پرسش‌های دانش‌آموز به معلم هنوز در ماژول جداگانه ثبت می‌شوند؛ هدف پاسخ‌گویی ۴۸ ساعت است.",
        },
        "qualification": qualification_row,
        "note_fa": "شاخص‌های آموزشی و مدیریتی جدا نگه داشته می‌شوند؛ بدون امتیاز کل و بدون قضاوت خودکار.",
    }


# ==============================================================================
# §11 مقایسه با مدرسه/استان + §12 شبیه‌ساز «اگر فردا امتحان بود»
# ==============================================================================


async def _agg_scope(db: AsyncSession, student_ids: list[int]) -> dict:
    """میانگین تسط/ماندگاری یک مجموعه دانش‌آموز (تجمیعی و ناشناس)."""
    if not student_ids:
        return {"students": 0, "mastery": None, "retention": None}
    states = [
        st
        for st in await _states_for_students(db, student_ids)
        if st.evidence_count >= 3
    ]
    if not states:
        return {"students": len(student_ids), "mastery": None, "retention": None}
    return {
        "students": len(student_ids),
        "mastery": round(sum(st.effective_mastery for st in states) / len(states), 1),
        "retention": round(sum(st.retention for st in states) / len(states), 3),
    }


async def _cause_shares(db: AsyncSession, student_ids: list[int]) -> dict[str, float]:
    if not student_ids:
        return {}
    errors = (
        (await db.execute(select(ErrorRecord).where(ErrorRecord.student_user_id.in_(student_ids)))).scalars()
    )
    counter = Counter(e.cause for e in errors)
    total = sum(counter.values())
    if not total:
        return {}
    return {c: round(100.0 * n / total, 1) for c, n in counter.items()}


async def class_compare(db: AsyncSession, class_id: int) -> dict:
    """§11 «کلاس شما / میانگین مدرسه / میانگین استان» — فقط تجمیع ناشناس، بدون
    فهرست اسمی هیچ مدرسهٔ دیگری (§18 سند معلم)."""
    cls = await db.get(ClassRoom, class_id)
    if cls is None:
        raise LookupError("کلاس یافت نشد")
    school = await db.get(School, cls.school_id)

    class_ids = [s.user_id for s in await _class_students(db, class_id)]
    school_ids = [
        p.user_id
        for p in (
            await db.execute(select(StudentProfile).where(StudentProfile.school_id == cls.school_id))
        ).scalars()
    ]
    province_ids: list[int] = []
    if school is not None:
        province_ids = [
            row
            for row in (
                await db.execute(
                    select(StudentProfile.user_id)
                    .join(School, School.id == StudentProfile.school_id)
                    .where(School.province_id == school.province_id)
                )
            ).scalars()
        ]

    me = await _agg_scope(db, class_ids)
    sc = await _agg_scope(db, school_ids)
    pv = await _agg_scope(db, province_ids)

    share_class = await _cause_shares(db, class_ids)
    share_school = await _cause_shares(db, school_ids)

    dominant_gap_fa = None
    if share_class:
        gap_cause = max(
            share_class,
            key=lambda c: share_class[c] - share_school.get(c, 0.0),
        )
        gap = round(share_class[gap_cause] - share_school.get(gap_cause, 0.0), 1)
        if gap > 0:
            dominant_gap_fa = (
                f"تفاوت اصلی در «{CAUSE_FA.get(gap_cause, gap_cause)}» است: "
                f"{share_class[gap_cause]}٪ خطاهای کلاس در برابر {share_school.get(gap_cause, 0.0)}٪ مدرسه — "
                f"اگر مدرسه و استان هم همین الگو را داشته باشند مشکل عمومی‌تر است، وگرنه ویژهٔ همین کلاس."
            )

    pattern_fa = "برای تشخیص الگو به دادهٔ بیشتر نیاز است"
    if me["mastery"] is not None and sc["mastery"] is not None and pv["mastery"] is not None:
        if me["mastery"] < sc["mastery"] <= pv["mastery"]:
            pattern_fa = "کلاس شما از مدرسه و مدرسه از استان پایین‌تر است — الگو عمومی‌تر از یک کلاس است"
        elif me["mastery"] < sc["mastery"]:
            pattern_fa = "کلاس شما از میانگین مدرسه پایین‌تر است — احتمالاً مشکل ویژهٔ همین کلاس است"
        elif me["mastery"] >= sc["mastery"]:
            pattern_fa = "کلاس شما در سطح یا بالاتر از میانگین مدرسه است"

    return {
        "class_id": class_id,
        "class_name": cls.name,
        "class": me,
        "school": {**sc, "name": school.name if school else None},
        "province": {**pv, "name": school.name if False else (None if school is None else None)},
        "cause_share_class": share_class,
        "cause_share_school": share_school,
        "dominant_gap_fa": dominant_gap_fa,
        "pattern_fa": pattern_fa,
        "note_fa": "مقایسه فقط برای تشخیص الگوست، نه رتبه‌بندی معلم/مدرسه — داده‌ها تجمیعی و ناشناس‌اند.",
    }


READY_BUCKETS = (
    ("mastered", "مسلط", 85.0),
    ("ready", "نسبتاً آماده", 70.0),
    ("review", "نیازمند مرور", 50.0),
    ("repair", "نیازمند ترمیم", 0.0),
)

READY_WEIGHTS = {"mastered": 1.0, "ready": 0.75, "review": 0.4, "repair": 0.1}


def _bucket_counts(values: list[float]) -> tuple[dict[str, int], float | None]:
    counts = {k: 0 for k, _, _ in READY_BUCKETS}
    if not values:
        return counts, None
    for v in values:
        for key, _, floor in READY_BUCKETS:
            if v >= floor:
                counts[key] += 1
                break
    estimate = round(
        sum(READY_WEIGHTS[k] * counts[k] for k, _, _ in READY_BUCKETS) / len(values) * 100, 1
    )
    return counts, estimate


async def readiness_snapshot(db: AsyncSession, class_id: int, topic_id: int | None = None) -> dict:
    """§12.1 «اگر فردا از این فصل امتحان بگیرم» — آمادگی لحظه‌ای کلاس."""
    per_student = await _class_topic_mastery(db, class_id, topic_id)
    counts, estimate = _bucket_counts(list(per_student.values()))
    topic = await db.get(Topic, topic_id) if topic_id else None
    return {
        "class_id": class_id,
        "topic_id": topic_id,
        "topic_title": topic.title_fa if topic else None,
        "students": len(per_student),
        "counts": counts,
        "estimate_pct": estimate,
        "buckets_fa": {k: label for k, label, _ in READY_BUCKETS},
        "note_fa": "برآورد تشخیصی از وضعیت فعلی کلاس است، نه پیش‌بینی قطعی نمره.",
    }


async def simulate_readiness(
    db: AsyncSession,
    class_id: int,
    *,
    topic_id: int | None = None,
    practice_quality: float | None = None,
    retention_boost: float = 0.0,
    participation: float | None = None,
) -> dict:
    """§12.2 شبیه‌ساز آمادگی: ورودی‌های معلم (کیفیت تمرین، مرور فاصله‌دار،
    مشارکت) ← بازمحاسبهٔ تسط مؤثر (E = M×(0.6+0.4R)) ← آمادگی پروژکتشده +
    فهرست ریسک‌ها (مبحث، زمان، خطاهای تکراری)."""
    settings = get_settings()
    baseline = await readiness_snapshot(db, class_id, topic_id)
    students = await _class_students(db, class_id)
    ids = [s.user_id for s in students]
    metrics = await student_metrics(db, ids)
    per_student = await _class_topic_mastery(db, class_id, topic_id)

    # وضعیت مرجع: تکمیل تمرین و مشارکت فعلی کلاس
    plan_vals = [m["progress_pct"] for m in metrics.values() if m["progress_pct"] is not None]
    current_plan = round(sum(plan_vals) / len(plan_vals), 1) if plan_vals else 0.0
    participants = sum(1 for m in metrics.values() if m["evidence_count"] >= settings.evidence_min_for_status)
    current_participation = round(100.0 * participants / len(ids), 1) if ids else 0.0

    practice_uplift = 0.0
    if practice_quality is not None:
        practice_uplift = (float(practice_quality) - current_plan) * 0.12
    participation_uplift = 0.0
    if participation is not None:
        participation_uplift = (float(participation) - current_participation) * 0.08
    boost = max(0.0, min(0.4, float(retention_boost or 0.0)))

    projected_values: list[float] = []
    for sid, e_val in per_student.items():
        row = metrics.get(sid) or {"mastery": e_val, "retention": 0.0}
        r_val = min(1.0, max(0.0, float(row["retention"])))
        denom = 0.6 + 0.4 * r_val
        m_est = (e_val / denom) if denom > 0 else e_val
        m_new = max(0.0, min(100.0, m_est + practice_uplift + participation_uplift))
        r_new = min(1.0, r_val + boost)
        projected_values.append(round(m_new * (0.6 + 0.4 * r_new), 1))

    p_counts, p_estimate = _bucket_counts(projected_values)
    delta = (
        round(p_estimate - baseline["estimate_pct"], 1)
        if (p_estimate is not None and baseline["estimate_pct"] is not None)
        else None
    )

    # ریسک‌ها: مباحث ضعیف، دانش‌آموزان کم‌زمان/پرخطا، خطاهای تکراری
    radar = await class_radar(db, class_id)
    weak_topics = [
        {"topic_id": r["topic_id"], "title": r["title"], "mastery": r["avg_mastery"]}
        for r in radar["rows"]
        if r["status"] in ("weak", "critical")
    ][:5]
    time_students = sum(
        1 for m in metrics.values() if m["error_causes"].get("time_management", 0) > 0
    )
    repeat_causes = Counter()
    for m in metrics.values():
        repeat_causes.update(m["error_causes"])

    return {
        "class_id": class_id,
        "topic_id": topic_id,
        "baseline": baseline,
        "projected": {
            "counts": p_counts,
            "estimate_pct": p_estimate,
            "buckets_fa": baseline["buckets_fa"],
        },
        "delta_pct": delta,
        "inputs": {
            "practice_quality": practice_quality,
            "current_plan_completion_pct": current_plan,
            "retention_boost": boost,
            "participation": participation,
            "current_participation_pct": current_participation,
        },
        "risks": {
            "weak_topics": weak_topics,
            "time_problem_students": time_students,
            "repeat_error_causes": [
                {"cause": c, "cause_fa": CAUSE_FA.get(c, c), "count": n}
                for c, n in repeat_causes.most_common(4)
            ],
        },
        "note_fa": "شبیه‌ساز بر اساس مدل تسط مؤثر (E = M×(0.6+0.4R)) بازمحاسبه می‌شود؛ خروجی برآورد است، نه نمرهٔ قطعی.",
    }


# ==============================================================================
# §14 گزارش والدین توسط معلم — تولید از دادهٔ موجود، قابل ویرایش پیش از ارسال
# ==============================================================================


async def build_parent_report(db: AsyncSession, class_id: int, student_id: int) -> dict:
    """§14 سند معلم: نقاط قوت، مباحث نیازمند تمرین، خطاهای پرتکرار، روند نسبت
    به آزمون قبلی و اقدام پیشنهادی — بدون اطلاعات سایر دانش‌آموزان."""
    await _profile_in_class(db, class_id, student_id)
    settings = get_settings()
    m = (await student_metrics(db, [student_id]))[student_id]
    topics = {t.id: t for t in (await db.execute(select(Topic))).scalars()}
    states = await _states_for_students(db, [student_id])

    ranked = sorted(states, key=lambda st: -st.effective_mastery)
    strengths = [
        topics[st.topic_id].title_fa if st.topic_id in topics else f"#{st.topic_id}"
        for st in ranked[:3]
        if st.effective_mastery >= settings.threshold_consolidating
    ]
    practice_needed = [
        {
            "title": topics[st.topic_id].title_fa if st.topic_id in topics else f"#{st.topic_id}",
            "mastery": st.effective_mastery,
        }
        for st in sorted(ranked, key=lambda s: s.effective_mastery)
        if st.effective_mastery < settings.threshold_consolidating
    ][:3]

    repeats = sorted(m["error_causes"].items(), key=lambda kv: -kv[1])
    repeat_lines = [
        f"{CAUSE_FA.get(c, c)} ({n} بار)" for c, n in repeats[:3]
    ]

    # روند نسبت به آزمون قبلی (دو آخرین آزمون تصحیح‌شده)
    attempts = list(
        (
            await db.execute(
                select(ExamAttempt)
                .where(
                    ExamAttempt.student_user_id == student_id,
                    ExamAttempt.status == "graded",
                    ExamAttempt.percent.is_not(None),
                )
                .order_by(ExamAttempt.id.desc())
                .limit(2)
            )
        ).scalars()
    )
    trend_fa = "هنوز دو آزمون تصحیح‌شده برای مقایسه ثبت نشده است"
    if len(attempts) >= 2:
        delta = round(attempts[0].percent - attempts[1].percent, 1)
        trend_fa = f"روند نسبت به آزمون قبلی: {'+' if delta >= 0 else ''}{delta} درصد"

    need = classify_need(
        e=m["mastery"],
        r=m["retention"],
        progress_pct=m["progress_pct"],
        repeat_count=m["open_errors"],
        prereq_weak=m["prereq_weak"],
    )
    action = NEED_ACTION_FA[need]
    if practice_needed:
        action = f"{action} — تا پایان هفته روی «{practice_needed[0]['title']}»"

    body_lines = [
        f"تسط کلی: {round(m['mastery'])}٪ · ماندگاری: {round(m['retention'] * 100)}٪",
        "نقاط قوت: " + ("، ".join(strengths) if strengths else "هنوز مبحثی به تثبیت نرسیده است"),
        "مباحث نیازمند تمرین: "
        + ("، ".join(f"{p['title']} ({round(p['mastery'])}٪)" for p in practice_needed) if practice_needed else "—"),
        ("خطاهای پرتکرار: " + "، ".join(repeat_lines)) if repeat_lines else "خطای پرتکرار ثبت نشده است",
        trend_fa,
        f"اقدام پیشنهادی: {action}",
    ]
    user = await db.get(User, student_id)
    title = f"گزارش یادگیری {user.full_name if user else f'#{student_id}'}"

    return {
        "class_id": class_id,
        "student_id": student_id,
        "student_name": user.full_name if user else None,
        "title_fa": title,
        "body_fa": "\n".join(body_lines),
        "sections": {
            "strengths": strengths,
            "practice_needed": practice_needed,
            "repeats": repeat_lines,
            "trend_fa": trend_fa,
            "action_fa": action,
        },
        "note_fa": "جزئیات سؤال‌به‌سؤال و اطلاعات سایر دانش‌آموزان در این گزارش نمایش داده نمی‌شود؛ پیش از ارسال می‌توانید متن را ویرایش کنید.",
    }


