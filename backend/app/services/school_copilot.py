"""دستیار هوشمند مدیر مدرسه (سند مدیر مدرسه §16 و §18).

§16: پرسش‌های تحلیلی مدیر روی «داده تجمیعی کل مدرسه» (نه SLM یک
دانش‌آموز) با معماری مشابه دستیار دانش‌آموز: تشخیص نیت → بازیابی
داده واقعی → پاسخ شفاف با «منابع» — اما عمداً بدون کش معنایی سراسری،
چون پاسخ حاوی داده اختصاصی همین مدرسه است و نباید به مدرسه دیگری
برسد (حریم خصوصی §20: حوزه دسترسی مدیر «school» است).

§18: پیشنهاد اقدام با اختیار مدیر — سیستم پیشنهاد می‌سازد ولی فقط با
تأیید، ویرایش یا رد مدیر «اجرا» می‌شود؛ هوش مصنوعی copilot است، نه
تصمیم‌گیرنده. همه پاسخ‌ها و تصمیم‌ها با رویداد ممیزی ثبت می‌شوند.

قاعده صداقت داده: هیچ عددی ساخته نمی‌شود؛ اگر داده‌ای (مثلاً دو دوره
آزمون) کافی نباشد، پاسخ همان می‌گوید."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.assessment import Exam, ExamAttempt
from app.models.catalog import Book, Chapter, Topic
from app.models.org import ClassRoom, ClassTeacherAssignment, StudentProfile, User
from app.models.school_copilot import (
    SchoolCopilotConversation,
    SchoolCopilotMessage,
    SchoolSuggestion,
)
from app.models.slm import ErrorRecord, StudentTopicState
from app.services import assistant
from app.services import school as school_svc
from app.services.slm import status_of

DISCLAIMER_NOTE_FA = (
    "این تحلیل از داده تجمیعی همین مدرسه ساخته شده است؛ "
    "copilot است، نه تصمیم‌گیرنده — تصمیم نهایی همیشه با مدیر (§16)."
)

NO_DATA_FA = "داده کافی برای این پرسش در مدرسه ثبت نشده است؛ عددی حدس نمی‌زنم."

SUBJECT_WORDS: dict[str, str] = {
    "ریاضی": "math",
    "فیزیک": "physics",
    "شیمی": "chemistry",
    "زیست": "biology",
    "عربی": "arabic",
    "فارسی": "persian",
    "انگلیسی": "english",
    "تاریخ": "history",
    "جغرافیا": "geography",
    "دین": "religion",
}

GRADE_WORDS: dict[str, str] = {
    "هفتم": "grade_7",
    "هشتم": "grade_8",
    "نهم": "grade_9",
    "دهم": "grade_10",
    "یازدهم": "grade_11",
    "دوازدهم": "grade_12",
}


def fa_num(n: float | int) -> str:
    """رقم فارسی برای متن پاسخ‌ها."""
    if isinstance(n, float) and n == int(n):
        n = int(n)
    return str(n).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def detect_intent(norm: str) -> str:
    """تشخیص نیت از متن نرمال‌شده (کلیدها خودشان نرمال شده‌اند)."""
    if "شورا" in norm and ("آموزشی" in norm or "مهم" in norm or "جلسه" in norm):
        return "council_agenda"
    if "مداخله" in norm and ("پیشرفت نکرده" in norm or "پیشرفت نشده" in norm or "هنوز" in norm):
        return "no_progress"
    if "بزرگ ترین مشکل" in norm or "بزرگترین مشکل" in norm or "مشکل آموزشی" in norm:
        return "biggest_problem"
    if "غیر عادی" in norm or ("الگو" in norm and "عادی" in norm) or "نیاز به بررسی" in norm:
        return "unusual_pattern"
    if "مبحث" in norm or "مباحث" in norm:
        return "weak_topics"
    if "افت" in norm and ("کلاس" in norm or "داشته" in norm):
        return "class_drop"
    return "overview"


def _parse_grade(norm: str) -> str | None:
    for word, code in GRADE_WORDS.items():
        if word in norm:
            return code
    m = re.search(r"(?:پایه|پايه)\s+(\d+)", norm)
    if m:
        return f"grade_{m.group(1)}"
    return None


def _parse_subject(norm: str) -> str | None:
    for word, code in SUBJECT_WORDS.items():
        if word in norm:
            return code
    return None


# ------------------------- بازیابی داده (RAG سبک روی تجمیع‌ها) -------------------------


async def _school_student_ids(db: AsyncSession, school_id: int) -> list[int]:
    profiles = (
        await db.execute(select(StudentProfile.user_id).where(StudentProfile.school_id == school_id))
    ).scalars().all()
    return list(profiles)


async def _school_classes(db: AsyncSession, school_id: int) -> list[ClassRoom]:
    return list(
        (await db.execute(select(ClassRoom).where(ClassRoom.school_id == school_id))).scalars()
    )


async def _topic_subject_map(db: AsyncSession) -> dict[int, str]:
    """topic_id → کد درس (از راه فصل → کتاب). برای فیلتر «ریاضی» در پرسش."""
    chapters = (await db.execute(select(Chapter.id, Chapter.book_id))).all()
    books = {b.id: b.subject for b in (await db.execute(select(Book))).scalars()}
    topic_rows = (await db.execute(select(Topic.id, Topic.chapter_id))).all()
    chapter_book = {cid: bid for cid, bid in chapters}
    return {tid: books.get(chapter_book.get(ch_id), "") for tid, ch_id in topic_rows}


async def _status_counts(db: AsyncSession, student_ids: list[int]) -> dict[str, int]:
    counts = {"critical": 0, "weak": 0, "consolidating": 0, "mastered": 0, "unknown": 0}
    if not student_ids:
        return counts
    states = (
        (
            await db.execute(
                select(StudentTopicState).where(StudentTopicState.student_user_id.in_(student_ids))
            )
        )
        .scalars()
        .all()
    )
    for st in states:
        counts[status_of(st.effective_mastery, st.evidence_count)] += 1
    return counts


async def _aggregate_weak_topics(
    db: AsyncSession,
    school_id: int,
    subject: str | None = None,
    grade: str | None = None,
) -> list[dict]:
    """مباحث ضعیف/بحرانی مدرسه → [{topic_id, title, weak_students, classes}].
    فیلتر پایه روی کلاس و فیلتر درس روی کتابِ مبحث اعمال می‌شود."""
    classes = await _school_classes(db, school_id)
    if grade:
        classes = [c for c in classes if c.grade == grade]
    subj_map = await _topic_subject_map(db) if subject else {}
    titles = await school_svc._topic_titles(db)

    acc: dict[int, dict] = {}
    for cls in classes:
        for st in await school_svc._states_for_class(db, cls.id):
            st_status = status_of(st.effective_mastery, st.evidence_count)
            if st_status not in ("weak", "critical"):
                continue
            if subject and subj_map.get(st.topic_id) != subject:
                continue
            row = acc.setdefault(
                st.topic_id,
                {"topic_id": st.topic_id, "title": titles.get(st.topic_id, f"#{st.topic_id}"), "weak_students": 0, "classes": set()},
            )
            row["weak_students"] += 1
            row["classes"].add(cls.name)

    rows = sorted(acc.values(), key=lambda r: -r["weak_students"])
    for r in rows:
        r["classes"] = sorted(r["classes"])
    return rows


async def _class_drop_rows(db: AsyncSession, school_id: int) -> tuple[list[dict], list[str]]:
    """کلاس‌های دارای افت (§7/§2): هر درسِ فعال مدرسه مقایسه می‌شود."""
    links = (
        (
            await db.execute(
                select(ClassTeacherAssignment.subject)
                .join(ClassRoom, ClassRoom.id == ClassTeacherAssignment.class_id)
                .where(
                    ClassRoom.school_id == school_id,
                    ClassTeacherAssignment.status == "active",
                )
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    drops: list[dict] = []
    notes: list[str] = []
    for subject in links:
        cmp = await school_svc.compare_classes(db, school_id, subject)
        if not cmp["comparison_valid"]:
            notes.append(cmp["min_group_note"])
        for row in cmp["rows"]:
            if row.get("drop_flag"):
                drops.append(
                    {
                        "class_id": row["class_id"],
                        "class_name": row.get("class_name") or row["class_id"],
                        "subject": subject,
                        "teacher": (row.get("teacher") or {}).get("full_name"),
                        "gap": row.get("gap_vs_school_avg"),
                        "mastery": row.get("avg_mastery"),
                    }
                )
    drops.sort(key=lambda d: d["gap"] if d["gap"] is not None else 0)
    return drops, notes


async def _no_progress_students(db: AsyncSession, school_id: int) -> list[dict]:
    """دانش‌آموزانی که دست‌کم دو چرخه مداخله (رفع/بازگشت) داشته‌اند ولی هنوز
    خطا باز یا بازگشته دارد — قاعده قطعی و قابل توضیح، بدون حدس."""
    student_ids = await _school_student_ids(db, school_id)
    if not student_ids:
        return []
    errors = (
        (await db.execute(select(ErrorRecord).where(ErrorRecord.student_user_id.in_(student_ids))))
        .scalars()
        .all()
    )
    per_user: dict[int, Counter] = defaultdict(Counter)
    for e in errors:
        per_user[e.student_user_id][e.status] += 1

    out: list[dict] = []
    for uid, c in per_user.items():
        cycles = c.get("resolved", 0) + c.get("relapsed", 0)
        still_open = c.get("open", 0) + c.get("in_remediation", 0) + c.get("relapsed", 0)
        if cycles >= 2 and still_open >= 1:
            out.append(
                {
                    "user_id": uid,
                    "cycles": cycles,
                    "open": still_open,
                    "relapsed": c.get("relapsed", 0),
                }
            )
    if not out:
        return []
    users = {
        u.id: u
        for u in (
            await db.execute(select(User).where(User.id.in_([r["user_id"] for r in out])))
        ).scalars()
    }
    for r in out:
        u = users.get(r["user_id"])
        r["full_name"] = u.full_name if u else None
    out.sort(key=lambda r: -r["cycles"])
    return out


async def _period_comparison(db: AsyncSession, school_id: int, student_ids: list[int]) -> dict:
    """میانگین درصد آزمون‌ها به تفکیک دوره (دوره‌های دارای آزمون با شناسه دوره)."""
    exams = (
        (
            await db.execute(
                select(Exam).where(
                    Exam.period_id.is_not(None),
                    (Exam.school_id == school_id) | (Exam.class_id.is_not(None)),
                )
            )
        )
        .scalars()
        .all()
    )
    exam_ids = [e.id for e in exams]
    if not exam_ids or not student_ids:
        return {"available": False, "periods": []}

    attempts = (
        (
            await db.execute(
                select(ExamAttempt)
                .where(
                    ExamAttempt.exam_id.in_(exam_ids),
                    ExamAttempt.student_user_id.in_(student_ids),
                    ExamAttempt.percent.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    by_period: dict[int, list[float]] = defaultdict(list)
    exam_period = {e.id: e.period_id for e in exams}
    for a in attempts:
        by_period[exam_period[a.exam_id]].append(float(a.percent))

    periods = sorted(
        ({"period_id": pid, "avg": round(sum(v) / len(v), 1), "n": len(v)} for pid, v in by_period.items() if v),
        key=lambda p: p["period_id"],
    )
    if len(periods) >= 2:
        prev, last = periods[-2], periods[-1]
        return {
            "available": True,
            "periods": periods,
            "delta": round(last["avg"] - prev["avg"], 1),
        }
    return {"available": False, "periods": periods}


# ------------------------- پاسخ‌سازی هر نیت -------------------------


def _src(kind: str, id_: int, title: str) -> dict:
    return {"type": kind, "id": id_, "title": title}


async def _answer_overview(db: AsyncSession, school_id: int) -> tuple[str, list[dict]]:
    student_ids = await _school_student_ids(db, school_id)
    classes = await _school_classes(db, school_id)
    counts = await _status_counts(db, student_ids)
    flags = await school_svc.attention_flags(db, school_id)
    statuses = counts["critical"] + counts["weak"] + counts["consolidating"] + counts["mastered"]
    sources: list[dict] = []

    lines = [f"مدرسه: {fa_num(len(classes))} کلاس، {fa_num(len(student_ids))} دانش‌آموز ثبت‌شده."]
    if statuses:
        lines.append(
            "وضعیت مباحث دانش‌آموزان: "
            f"بحرانی {fa_num(counts['critical'])}، ضعیف {fa_num(counts['weak'])}، "
            f"در حال تثبیت {fa_num(counts['consolidating'])}، مسلط {fa_num(counts['mastered'])}، "
            f"بدون داده {fa_num(counts['unknown'])}."
        )
    else:
        lines.append("هنوز شواهد یادگیری برای دانش‌آموزان ثبت نشده است.")
    if flags["flags"]:
        lines.append(
            f"{fa_num(len(flags['flags']))} پرچم «نیازمند بررسی» فعال است — تب «نیازمند بررسی» را ببینید."
        )
        sources += [_src("class", f["class_id"], f"کلاس {f['class_name']}") for f in flags["flags"][:5]]
    lines.append("برای نمونه بپرسید: «بزرگ‌ترین مشکل آموزشی مدرسه چیست؟» یا «کدام کلاس‌ها بیشترین افت را داشته‌اند؟»")
    return "\n".join(lines), sources


async def _answer_biggest_problem(db: AsyncSession, school_id: int) -> tuple[str, list[dict]]:
    student_ids = await _school_student_ids(db, school_id)
    if not student_ids:
        return NO_DATA_FA, []

    counts = await _status_counts(db, student_ids)
    sources: list[dict] = []

    # خطاهای غالب مدرسه
    errors = (
        (await db.execute(select(ErrorRecord).where(ErrorRecord.student_user_id.in_(student_ids))))
        .scalars()
        .all()
    )
    causes = Counter(e.cause for e in errors)

    # ضعیف‌ترین کلاس‌ها (میانگین تسط)
    class_rows: list[dict] = []
    for cls in await _school_classes(db, school_id):
        summary = await school_svc.class_subject_summary(db, cls.id)
        if summary["avg_mastery"] is not None:
            class_rows.append({"name": cls.name, "mastery": summary["avg_mastery"]})
    class_rows.sort(key=lambda r: r["mastery"])

    lines: list[str] = []
    weak_total = counts["critical"] + counts["weak"]
    if weak_total:
        lines.append(
            f"از {fa_num(counts['critical'] + counts['weak'] + counts['consolidating'] + counts['mastered'])} وضعیت ثبت‌شده، "
            f"{fa_num(weak_total)} مورد بحرانی/ضعیف است."
        )
    if causes:
        total = sum(causes.values())
        top = ", ".join(
            f"«{school_svc.CAUSE_SEVERITY_FA.get(c, c).split('—')[0].strip()}» {fa_num(n)} مورد ({fa_num(round(100 * n / total))}٪)"
            for c, n in causes.most_common(3)
        )
        lines.append(f"بیشترین سهم خطا: {top}.")
        sources += [_src("error_cause", 0, c) for c, _ in causes.most_common(3)]
    if class_rows:
        w = class_rows[0]
        lines.append(f"ضعیف‌ترین کلاس از نظر میانگین تسط: کلاس {w['name']} با {fa_num(w['mastery'])}٪.")

    period = await _period_comparison(db, school_id, student_ids)
    if period["available"]:
        arrow = "رشد" if period["delta"] >= 0 else "افت"
        lines.append(
            f"مقایسه دو دوره اخیر آزمون: میانگین {fa_num(period['periods'][-2]['avg'])}٪ → "
            f"{fa_num(period['periods'][-1]['avg'])}٪ ({arrow} {fa_num(abs(period['delta']))} واحد)."
        )
        sources += [_src("period", p["period_id"], f"دوره {fa_num(p['period_id'])}") for p in period["periods"][-2:]]
    elif period["periods"]:
        lines.append("برای مقایسه «دو دوره اخیر» هنوز آزمون دارای دوره کافی ثبت نشده است؛ عددی ساخته نمی‌شود.")
    else:
        lines.append("آزمون دوره‌دار برای مقایسه دوره‌ها ثبت نشده است.")

    if not lines:
        return NO_DATA_FA, []
    return "\n".join(lines), sources


async def _answer_class_drop(db: AsyncSession, school_id: int) -> tuple[str, list[dict]]:
    drops, notes = await _class_drop_rows(db, school_id)
    if not drops:
        note = " «" + notes[0] + "»" if notes else ""
        return (
            "کلاسی با افت ≥ آستانه نسبت به هم‌درس‌ها پیدا نشد." + (f" توجه: {note}" if note else ""),
            [],
        )
    lines = ["کلاس‌های دارای افت (حداقل ۱۰ واحد پایین‌تر از میانگین هم‌درس‌ها):"]
    sources: list[dict] = []
    for d in drops:
        teacher = f" — معلم {d['teacher']}" if d["teacher"] else ""
        lines.append(
            f"• کلاس {d['class_name']} ({d['subject']}): "
            f"{fa_num(abs(d['gap']))} واحد پایین‌تر، تسط {fa_num(d['mastery'])}٪{teacher}"
        )
        sources.append(_src("class", d["class_id"], f"کلاس {d['class_name']}"))
    lines.append("این پرچم است، نه حکم درباره معلم؛ عوامل زمینه‌ای را در مقایسه معلمان ببینید (§8).")
    return "\n".join(lines), sources


async def _answer_weak_topics(
    db: AsyncSession, school_id: int, subject: str | None, grade: str | None
) -> tuple[str, list[dict]]:
    rows = await _aggregate_weak_topics(db, school_id, subject=subject, grade=grade)
    if not rows:
        # بدون تطابق فیلتر → گزارش صادقانه (با اعلام اعمال‌نشدن فیلتر)
        scope = []
        if grade:
            scope.append(f"پایه {grade}")
        if subject:
            scope.append(f"درس {subject}")
        suffix = f" برای {' و '.join(scope)}" if scope else ""
        return f"مبحث ضعیفی با این فیلترها پیدا نشد{suffix}.", []

    head = ["مباحث با بیشترین دانش‌آموز ضعیف/بحرانی:"]
    if grade or subject:
        head = ["مباحث ضعیف مطابق پرسش شما:"]
    sources: list[dict] = []
    for r in rows[:5]:
        head.append(
            f"• «{r['title']}» — {fa_num(r['weak_students'])} دانش‌آموز در کلاس‌های {', '.join(r['classes'])}"
        )
        sources.append(_src("topic", r["topic_id"], r["title"]))
    head.append("ریشه‌یابی علت خطا (مفهومی/پیش‌نیاز/محاسباتی) را از «تشخیص چندعاملی» همان کلاس شروع کنید.")
    return "\n".join(head), sources


async def _answer_no_progress(db: AsyncSession, school_id: int) -> tuple[str, list[dict]]:
    rows = await _no_progress_students(db, school_id)
    if not rows:
        return (
            "دانش‌آموزی با دست‌کم دو چرخه مداخله و پیشرفت ناکامل پیدا نشد — یا هنوز مداخله‌ای ثبت نشده است.",
            [],
        )
    lines = ["دانش‌آموزانی که بعد از دست‌کم دو مداخله هنوز خطای باز/بازگشته دارند:"]
    sources: list[dict] = []
    for r in rows[:8]:
        lines.append(
            f"• {r['full_name'] or '—'}: {fa_num(r['cycles'])} چرخه، {fa_num(r['open'])} خطا باز"
            + (f" ({fa_num(r['relapsed'])} بازگشت)" if r["relapsed"] else "")
        )
        sources.append(_src("student", r["user_id"], r["full_name"] or f"#{r['user_id']}"))
    lines.append("مشاهده فردی این دانش‌آموزان در «نمای فردی دانش‌آموز» با ثبت ممیزی انجام می‌شود (§20).")
    return "\n".join(lines), sources


async def _answer_unusual(db: AsyncSession, school_id: int) -> tuple[str, list[dict]]:
    flags = await school_svc.attention_flags(db, school_id)
    if not flags["flags"]:
        return "با آستانه‌های فعلی هیچ الگوی غیرعادی/پرچم «نیازمند بررسی» در مدرسه فعال نیست.", []
    lines = [f"{fa_num(len(flags['flags']))} کلاس/مورد برای بررسی (پرچم، نه قضاوت):"]
    sources: list[dict] = []
    for f in flags["flags"]:
        lines.append(f"• «{f['title_fa']}» — کلاس {f['class_name']}: {f['evidence_fa']}")
        lines.append(f"  اقدام پیشنهادی: {f['action_fa']}")
        sources.append(_src("class", f["class_id"], f"کلاس {f['class_name']}"))
    lines.append(flags["note_fa"])
    return "\n".join(lines), sources


async def _answer_council(db: AsyncSession, school_id: int) -> tuple[str, list[dict]]:
    flags = await school_svc.attention_flags(db, school_id)
    drops, _ = await _class_drop_rows(db, school_id)
    weak = await _aggregate_weak_topics(db, school_id)
    student_ids = await _school_student_ids(db, school_id)
    counts = await _status_counts(db, student_ids)

    items: list[str] = []
    sources: list[dict] = []
    if flags["flags"]:
        items.append(f"پرچم‌های فعال «نیازمند بررسی»: {fa_num(len(flags['flags']))} مورد (تب نیازمند بررسی).")
        sources += [_src("class", f["class_id"], f"کلاس {f['class_name']}") for f in flags["flags"][:4]]
    if drops:
        items.append(
            "کلاس‌های دارای افت: "
            + "، ".join(f"{d['class_name']} ({d['subject']})" for d in drops[:3])
            + "."
        )
        sources += [_src("class", d["class_id"], f"کلاس {d['class_name']}") for d in drops[:3]]
    if weak:
        items.append(
            "مباحث پرمخاطره: " + "، ".join(f"«{r['title']}» ({fa_num(r['weak_students'])} نفر)" for r in weak[:3]) + "."
        )
        sources += [_src("topic", r["topic_id"], r["title"]) for r in weak[:3]]
    if counts["critical"]:
        items.append(f"{fa_num(counts['critical'])} وضعیت «بحرانی» که تخصیص مداخله فوری می‌خواهد.")
    if not items:
        return "برای جلسه شورا مورد فوری‌ای از داده‌ها بیرون نمی‌آید؛ داشبورد مدرسه در وضعیت عادی است.", []
    head = ["مهم‌ترین موارد پیشنهادی برای جلسه شورای آموزشی هفته آینده (از داده‌های فعلی):"]
    head += [f"{fa_num(i + 1)}. {item}" for i, item in enumerate(items)]
    head.append("ترتيب نهایی و تصمیم با شماست؛ این فقط مرتب‌سازی داده‌محور است.")
    return "\n".join(head), sources


async def answer(db: AsyncSession, school_id: int, message: str) -> tuple[str, str, list[dict]]:
    """نیت + پاسخ + منابع. بدون کش سراسری (داده اختصاصی مدرسه)."""
    norm = assistant.normalize_query(message)
    intent = detect_intent(norm)

    if intent == "council_agenda":
        reply, sources = await _answer_council(db, school_id)
    elif intent == "no_progress":
        reply, sources = await _answer_no_progress(db, school_id)
    elif intent == "biggest_problem":
        reply, sources = await _answer_biggest_problem(db, school_id)
    elif intent == "unusual_pattern":
        reply, sources = await _answer_unusual(db, school_id)
    elif intent == "weak_topics":
        reply, sources = await _answer_weak_topics(db, school_id, _parse_subject(norm), _parse_grade(norm))
    elif intent == "class_drop":
        reply, sources = await _answer_class_drop(db, school_id)
    else:
        reply, sources = await _answer_overview(db, school_id)

    return f"{reply}\n\n{DISCLAIMER_NOTE_FA}", intent, sources


async def chat(
    db: AsyncSession,
    school_id: int,
    actor_user_id: int,
    message: str,
    conversation_id: int | None,
) -> dict:
    """حلقه کامل گفت‌وگو: ثبت پیام‌ها + پاسخ ریشه‌دار با منابع."""
    conv = await db.get(SchoolCopilotConversation, conversation_id) if conversation_id else None
    if conv is None or conv.school_id != school_id:
        conv = SchoolCopilotConversation(school_id=school_id, user_id=actor_user_id, title=message[:80])
        db.add(conv)
        await db.flush()

    db.add(SchoolCopilotMessage(conversation_id=conv.id, role="user", content=message))
    reply, intent, sources = await answer(db, school_id, message)
    db.add(
        SchoolCopilotMessage(
            conversation_id=conv.id,
            role="assistant",
            content=reply,
            intent=intent,
            sources=sources or None,
        )
    )
    await db.flush()
    return {
        "conversation_id": conv.id,
        "intent": intent,
        "reply": reply,
        "sources": sources,
        "model_tier": assistant.pick_tier(message),
        "note_fa": DISCLAIMER_NOTE_FA,
    }


async def list_conversations(db: AsyncSession, school_id: int) -> list[dict]:
    rows = (
        (
            await db.execute(
                select(SchoolCopilotConversation)
                .where(SchoolCopilotConversation.school_id == school_id)
                .order_by(SchoolCopilotConversation.id.desc())
            )
        )
        .scalars()
        .all()
    )
    return [{"id": c.id, "title": c.title, "created_at": c.created_at} for c in rows]


async def conversation_messages(db: AsyncSession, school_id: int, conversation_id: int) -> dict | None:
    conv = await db.get(SchoolCopilotConversation, conversation_id)
    if conv is None or conv.school_id != school_id:
        return None
    msgs = (
        (
            await db.execute(
                select(SchoolCopilotMessage)
                .where(SchoolCopilotMessage.conversation_id == conversation_id)
                .order_by(SchoolCopilotMessage.id)
            )
        )
        .scalars()
        .all()
    )
    return {
        "id": conv.id,
        "title": conv.title,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "intent": m.intent,
                "sources": m.sources,
                "created_at": m.created_at,
            }
            for m in msgs
        ],
    }


# ------------------------- §18 پیشنهاد اقدام و اختیار مدیر -------------------------


async def generate_suggestions(db: AsyncSession, school_id: int) -> list[SchoolSuggestion]:
    """پیشنهاد اقدام از پرچم‌های §5 + کلاس‌های دارای افت — بدون تکرار
    تا زمانی که پیشنهادِ بازِ همان عنوان وجود دارد (idempotent)."""
    existing = {
        (s.class_id, s.title_fa)
        for s in (
            await db.execute(
                select(SchoolSuggestion).where(
                    SchoolSuggestion.school_id == school_id,
                    SchoolSuggestion.status == "proposed",
                )
            )
        ).scalars()
    }
    created: list[SchoolSuggestion] = []

    def _add(class_id: int | None, subject: str | None, title: str, evidence: str, actions: list[str]) -> None:
        if (class_id, title) in existing:
            return
        created.append(
            SchoolSuggestion(
                school_id=school_id,
                class_id=class_id,
                subject=subject,
                title_fa=title,
                evidence_fa=evidence,
                actions_fa=actions,
                status="proposed",
            )
        )
        existing.add((class_id, title))

    flags = await school_svc.attention_flags(db, school_id)
    for f in flags["flags"]:
        _add(
            f["class_id"],
            f.get("subject"),
            f"{f['title_fa']} — کلاس {f['class_name']}",
            f"{f['evidence_fa']}. {f['action_fa']}.",
            [
                f["action_fa"],
                "بررسی عوامل زمینه‌ای (پیش‌نیازها، سختی آزمون، مشارکت در تمرین)",
                "تعیین مهلت بازبینی دو هفته‌ای و ثبت نتیجه",
            ],
        )

    drops, _ = await _class_drop_rows(db, school_id)
    for d in drops:
        _add(
            d["class_id"],
            d["subject"],
            f"افت کلاس {d['class_name']} در {d['subject']}",
            f"کلاس {d['class_name']} با {fa_num(abs(d['gap']))} واحد افت نسبت به هم‌درس‌ها "
            f"(تسط {fa_num(d['mastery'])}٪).",
            [
                "بررسی پیش‌نیازهای مباحث عقب‌افتاده",
                "یک جلسه مرور توسط معلم",
                "آزمون تشخیصی کوتاه برای ریشه‌یابی",
                "تمرین شخصی‌سازی‌شده برای دانش‌آموزان زیر آستانه",
                "بازآزمون بعد از ۷ روز و مقایسه با قبل",
            ],
        )

    if created:
        db.add_all(created)
        await db.flush()
    return created


async def decide_suggestion(
    db: AsyncSession,
    school_id: int,
    suggestion_id: int,
    actor_user_id: int,
    action: str,
    edited_actions: list[str] | None = None,
    note: str | None = None,
) -> SchoolSuggestion | None:
    """تأیید/ویرایش/رد پیشنهاد (§18). خارج از مدرسه → None (مجری 404 می‌دهد);
    تصمیم تکراری → ValueError (مجری 409)."""
    sugg = (
        (
            await db.execute(
                select(SchoolSuggestion).where(
                    SchoolSuggestion.id == suggestion_id,
                    SchoolSuggestion.school_id == school_id,
                )
            )
        )
        .scalars()
        .first()
    )
    if sugg is None:
        return None
    if sugg.status != "proposed":
        raise ValueError("برای این پیشنهاد قبلاً تصمیم گرفته شده است")

    if action == "approve":
        sugg.status = "approved"
        sugg.final_actions_fa = list(sugg.actions_fa)
    elif action == "edit":
        if not edited_actions:
            raise ValueError("برای ویرایش، فهرست اقدام‌های جدید الزامی است")
        sugg.status = "edited"
        sugg.final_actions_fa = list(edited_actions)
    elif action == "reject":
        sugg.status = "rejected"
        sugg.final_actions_fa = None
    else:
        raise ValueError("عملیات نامعتبر است (approve|edit|reject)")

    sugg.decided_by = actor_user_id
    sugg.decided_at = datetime.now(timezone.utc)
    sugg.decision_note = note
    await db.flush()
    return sugg
