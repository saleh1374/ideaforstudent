"""دستیار هوشمند معلم (سند پنل معلم §15 و §16).

§15: این دستیار از دستیار دانش‌آموز جداست: به «برش داده تجمیعی همان
کلاس» دسترسی دارد (نه SLM یک دانش‌آموز) و پرسش‌های تحلیلی + درخواست
ساخت محتوا را هم‌زمان پاسخ می‌دهد — با همان معماری تشخیص نیت →
بازیابی داده واقعی → پاسخ شفاف با «منابع» (بدون کش معنایی سراسری).

§16: copilot است، نه جایگزین معلم — هیچ پیشنهادی (ساخت آزمون، ارسال
تمرین، گزارش والدین، پیام به دانش‌آموز) بدون تأیید، ویرایش یا رد معلم
اجرا نمی‌شود. رویدادهای ممیزی: teacher_copilot_query و
ai_suggestion_approved/edited/rejected.

قاعده صداقت داده: هیچ عددی ساخته نمی‌شود؛ بدون داده کافی همان
گفته می‌شود."""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assessment import Exam
from app.models.catalog import Book
from app.models.exam_builder import ExamBuilderProfile
from app.models.org import ClassRoom, ClassTeacherAssignment, User
from app.models.slm import PlanTask
from app.models.teacher_copilot import (
    TeacherCopilotConversation,
    TeacherCopilotMessage,
    TeacherSuggestion,
)
from app.services import assistant
from app.services import exam_builder as eb_svc
from app.services import teacher as teacher_svc

DISCLAIMER_NOTE_FA = (
    "این تحلیل از داده تجمیعی همین کلاس ساخته شده است؛ "
    "copilot است، نه تصمیم‌گیرنده — اجرای هر پیشنهاد فقط با تأیید، "
    "ویرایش یا رد شما (§16)."
)

NO_DATA_FA = "داده کافی برای این پرسش در این کلاس ثبت نشده است؛ عددی حدس نمی‌زنم."

_TOKEN = re.compile(r"[؀-ۿa-zA-Z]+")


def fa_num(n: float | int) -> str:
    """رقم فارسی برای متن پاسخ‌ها."""
    if isinstance(n, float) and n == int(n):
        n = int(n)
    return str(n).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def detect_intent(norm: str) -> str:
    """تشخیص نیت از متن نرمال‌شده (§15 نمونه گفت‌وگو)."""
    if ("آزمون" in norm or "امتحان" in norm) and (
        "بساز" in norm or "ساخت" in norm or "طراحی" in norm or "بده" in norm
    ):
        return "build_exam"
    if "طرح درس" in norm or "برنامه درس" in norm:
        return "lesson_plan"
    if "ماندگاری" in norm and ("افت" in norm or "خوب" in norm or "نمره" in norm):
        return "retention_drop"
    if "مداخله" in norm or "بسته ترمیمی" in norm:
        return "intervention"
    if (
        ("چرا" in norm or "ریشه" in norm or "علت" in norm)
        and ("ضعیف" in norm or "ضعف" in norm or "کلاس" in norm)
    ) or "ریشه یابی" in norm:
        return "weak_cause"
    if "مبحث" in norm or "مباحث" in norm or "تحلیل" in norm or "کلاس" in norm:
        return "overview"
    return "overview"


# ------------------------- بازیابی داده (برش تجمیعی همان کلاس) -------------------------


def _src(kind: str, id_: int, title: str) -> dict:
    return {"type": kind, "id": id_, "title": title}


async def _class_subject(db: AsyncSession, cls: ClassRoom) -> str | None:
    """درس کلاس: از تخصیص فعال معلم‌ها، وگرنه از کتاب همان پایه."""
    link = (
        await db.execute(
            select(ClassTeacherAssignment)
            .where(ClassTeacherAssignment.class_id == cls.id, ClassTeacherAssignment.status == "active")
            .limit(1)
        )
    ).scalar_one_or_none()
    if link is not None and link.subject:
        return link.subject
    book = (await db.execute(select(Book).where(Book.grade == cls.grade).limit(1))).scalar_one_or_none()
    return book.subject if book else None


async def _match_topic(db: AsyncSession, radar: dict, message: str) -> dict | None:
    """مبحثِ هدف پرسش: تطبیق کلمه‌ای با عناوین رادار؛ وگرنه ضعیف‌ترین ردیف."""
    if not radar["rows"]:
        return None
    tokens = [t for t in _TOKEN.findall(message) if len(t) > 2]
    for row in radar["rows"]:
        if any(t in row["title"] or row["title"] in t for t in tokens):
            return row
    return radar["rows"][0]  # رادار بر اساس تسط صعودی مرتب است


# ------------------------- پاسخ‌سازی هر نیت -------------------------


async def _answer_overview(db: AsyncSession, class_id: int) -> tuple[str, list[dict]]:
    radar = await teacher_svc.class_radar(db, class_id)
    if not radar["rows"]:
        return NO_DATA_FA, []
    groups = await teacher_svc.need_groups(db, class_id)
    counts = {g["need"]: len(g["students"]) for g in groups["groups"]}

    lines = [
        f"کلاس: {fa_num(radar['total_students'])} دانش‌آموز، "
        f"{fa_num(len(radar['rows']))} مبحث با داده ثبت‌شده."
    ]
    weak = [r for r in radar["rows"] if r["weak_count"]]
    if weak:
        lines.append(
            "ضعیف‌ترین مباحث: "
            + "، ".join(
                f"«{r['title']}» (تسط {fa_num(r['avg_mastery'])}٪، {fa_num(r['weak_count'])} نفر نیازمند تمرین)"
                for r in weak[:3]
            )
            + "."
        )
    else:
        lines.append("هیچ مبحثی زیر آستانه تثبیت نیست؛ کلاس در مسیر پیشروی است.")
    if counts.get("intervention"):
        lines.append(f"{fa_num(counts['intervention'])} دانش‌آموز نیازمند مداخله آموزشی است.")
    if counts.get("retention_drop"):
        lines.append(
            f"{fa_num(counts['retention_drop'])} دانش‌آموز افت ماندگاری دارند — "
            "«دانش‌آموزانی که نمره‌شان خوب ولی ماندگاری‌شان در حال افت است» را بپرسید."
        )
    lines.append(
        "برای نمونه بپرسید: «چرا کلاسم در احتمال ضعیفه؟» یا "
        "«یک طرح درس برای ضعیف‌ترین مبحث پیش‌نویس کن»."
    )
    sources = [_src("topic", r["topic_id"], r["title"]) for r in radar["rows"][:3]]
    return "\n".join(lines), sources


async def _answer_weak_cause(
    db: AsyncSession, class_id: int, message: str
) -> tuple[str, list[dict]]:
    """ریشه‌یابی به زبان ساده (§15 نمونه: توزیع علت خطا با شمارش)."""
    radar = await teacher_svc.class_radar(db, class_id)
    target = await _match_topic(db, radar, message)
    if target is None:
        return NO_DATA_FA, []

    lines = [
        f"مبحث «{target['title']}»: میانگین تسط {fa_num(target['avg_mastery'])}٪ — "
        f"{fa_num(target['weak_count'])} نفر از {fa_num(target['total_students'])} نفر زیر آستانه تثبیت."
    ]
    sources = [_src("topic", target["topic_id"], target["title"])]
    if target.get("prereq_weak"):
        lines.append("پرچم ضعف پیش‌نیاز برای این مبحث فعال است.")

    causes: Counter = Counter(target.get("error_causes") or {})
    if causes:
        total = sum(causes.values())
        top = ", ".join(
            f"{eb_svc.CAUSE_FA.get(c, c)} ({fa_num(n)} مورد، {fa_num(round(100 * n / total))}٪)"
            for c, n in causes.most_common(3)
        )
        lines.append(f"بیشترین سهم خطا: {top}.")
        sources += [_src("error_cause", 0, eb_svc.CAUSE_FA.get(c, c)) for c, _ in causes.most_common(3)]
    else:
        lines.append("خطای ثبت‌شده‌ای برای این مبحث در دفترچه خطا وجود ندارد.")

    chain = await teacher_svc.root_cause_chain(db, class_id, target["topic_id"])
    lines.append(chain["diagnosis"])
    if chain["root"]["topic_id"] != target["topic_id"]:
        sources.append(_src("topic", chain["root"]["topic_id"], chain["root"]["title"]))
    return "\n".join(lines), sources


async def _answer_retention_drop(db: AsyncSession, class_id: int) -> tuple[str, list[dict]]:
    """نمونه §15: نمره خوب ولی ماندگاری در حال افت."""
    groups = await teacher_svc.need_groups(db, class_id)
    row = next((g for g in groups["groups"] if g["need"] == "retention_drop"), None)
    if row is None or not row["students"]:
        return (
            "دانش‌آموزی با ترکیب «نمره خوب + افت ماندگاری» در این کلاس شناسایی نشد — "
            "یا هنوز داده مرور/ماندگاری کافی ثبت نشده است.",
            [],
        )
    lines = [f"{fa_num(len(row['students']))} دانش‌آموز با نمره قابل قبول ولی افت ماندگاری:"]
    sources: list[dict] = []
    for st in row["students"][:8]:
        lines.append(
            f"• {st['full_name']}: تسط {fa_num(st['mastery'])}٪، ماندگاری {fa_num(round(st['retention'] * 100))}٪"
        )
        sources.append(_src("student", st["student_id"], st["full_name"]))
    lines.append(f"اقدام پیشنهادی: {row['action']} — «مداخله» را بپرسید یا کارت پیشنهاد بسازید.")
    return "\n".join(lines), sources


async def _answer_lesson_plan(
    db: AsyncSession, class_id: int, message: str
) -> tuple[str, list[dict]]:
    """پیش‌نویس طرح درس (§15 قابلیت) — خروجی متنی برای ویرایش معلم، نه اجرا."""
    radar = await teacher_svc.class_radar(db, class_id)
    target = await _match_topic(db, radar, message)
    if target is None:
        return NO_DATA_FA, []
    chain = await teacher_svc.root_cause_chain(db, class_id, target["topic_id"])
    cls = await db.get(ClassRoom, class_id)

    lines = [
        f"پیش‌نویس طرح درس — «{target['title']}» (کلاس {cls.name if cls else fa_num(class_id)}):",
        f"۱. هدف یادگیری: دانش‌آموزان بتوانند {target['title']} را با تسط حداقل {fa_num(70)}٪ انجام دهند.",
        f"۲. پیش‌نیاز: {chain['root']['title']} (میانگین فعلی {fa_num(chain['root']['mastery']) if chain['root']['mastery'] is not None else '—'}٪) — مرور کوتاه پیش از شروع.",
        "۳. تدریس: طرح گام‌به‌گام + مثال ساده؛ بر خطاهای غالب تمرکز شود"
        + (f" ({eb_svc.CAUSE_FA.get(Counter(target.get('error_causes') or {}).most_common(1)[0][0], '—')})" if target.get("error_causes") else "")
        + ".",
        f"۴. تمرین: {fa_num(max(target['weak_count'], 3))} نفر زیر آستانه تمرین هدفمند بگیرند؛ بقیه تمرین تثبیت.",
        f"۵. سنجش: آزمونک کوتاه پایان جلسه + مرور فاصله‌دار ۷ روزه.",
        "این پیش‌نویس است؛ پیش از استفاده ویرایش کنید.",
    ]
    sources = [_src("topic", target["topic_id"], target["title"])]
    return "\n".join(lines), sources


async def _answer_intervention(db: AsyncSession, class_id: int) -> tuple[str, list[dict]]:
    groups = await teacher_svc.need_groups(db, class_id)
    rows = [g for g in groups["groups"] if g["need"] in ("intervention", "behind") and g["students"]]
    if not rows:
        return "در حال حاضر دانش‌آموزی در گروه «مداخله آموزشی» یا «عقب‌ماندگی برنامه» نیست.", []
    lines: list[str] = []
    sources: list[dict] = []
    for g in rows:
        names = "، ".join(st["full_name"] for st in g["students"][:5])
        lines.append(f"• {g['label']} — {fa_num(len(g['students']))} نفر ({names}): {g['action']}")
        sources += [_src("student", st["student_id"], st["full_name"]) for st in g["students"][:5]]
    lines.append("برای اجرای این پیشنهاد، از «ساخت پیشنهاد» کارت بسازید و با تأیید/ویرایش/رد تصمیم بگیرید (§16).")
    return "\n".join(lines), sources


async def _propose_exam_suggestion(
    db: AsyncSession, class_id: int, message: str
) -> tuple[str, list[dict], list[TeacherSuggestion]]:
    """درخواست ساخت آزمون: پیش‌نویس blueprint + کارت پیشنهاد — اجرا فقط با تأیید (§16)."""
    radar = await teacher_svc.class_radar(db, class_id)
    target = await _match_topic(db, radar, message)
    goal = message.strip()
    cls = await db.get(ClassRoom, class_id)
    subject = await _class_subject(db, cls) if cls else None

    proposal = await eb_svc.propose_blueprint(
        db,
        goal=goal,
        exam_type="class_exam",
        topic_id=target["topic_id"] if target else None,
        grade=cls.grade if cls else None,
        subject=subject,
    )

    created: list[TeacherSuggestion] = []
    preview = "پیش‌نویس بلوپرینت قابل پیشنهاد نیست."
    if proposal.get("ok"):
        preview = proposal["summary_fa"]
        title = f"ساخت پیش‌نویس آزمون: {target['title'] if target else goal[:60]}"
        existing = (
            await db.execute(
                select(TeacherSuggestion).where(
                    TeacherSuggestion.class_id == class_id,
                    TeacherSuggestion.status == "proposed",
                    TeacherSuggestion.title_fa == title,
                )
            )
        ).scalars().first()
        if existing is None:
            sugg = TeacherSuggestion(
                class_id=class_id,
                kind="draft_exam",
                title_fa=title,
                evidence_fa=(
                    f"طبق درخواست شما «{goal}»: {proposal['summary_fa']} "
                    f"مبحث هدف: «{proposal['target_topic']['title']}»."
                ),
                actions_fa=[
                    "تأیید — ساخت پیش‌نویس آزمون در سازنده آزمون",
                    "ویرایش — تغییر هدف/عنوان پیش از ساخت",
                    "رد — بدون ساخت",
                ],
                payload={
                    "goal": goal,
                    "exam_type": "class_exam",
                    "topic_id": proposal["target_topic"]["topic_id"],
                },
                status="proposed",
            )
            db.add(sugg)
            await db.flush()
            created.append(sugg)

    reply = (
        f"{preview}\n\n"
        "کارت پیشنهاد «ساخت پیش‌نویس آزمون» ساخته شد؛ تا زمانی که تأیید نکنید چیزی ساخته نمی‌شود (§16)."
    )
    sources = [_src("topic", target["topic_id"], target["title"])] if target else []
    return reply, sources, created


async def answer(
    db: AsyncSession, class_id: int, message: str
) -> tuple[str, str, list[dict], list[TeacherSuggestion]]:
    """نیت + پاسخ + منابع + پیشنهادهای پیشنهادشدهٔ همین پیام (بدون اجرا)."""
    norm = assistant.normalize_query(message)
    intent = detect_intent(norm)
    created: list[TeacherSuggestion] = []

    if intent == "build_exam":
        reply, sources, created = await _propose_exam_suggestion(db, class_id, message)
    elif intent == "weak_cause":
        reply, sources = await _answer_weak_cause(db, class_id, message)
    elif intent == "retention_drop":
        reply, sources = await _answer_retention_drop(db, class_id)
    elif intent == "lesson_plan":
        reply, sources = await _answer_lesson_plan(db, class_id, message)
    elif intent == "intervention":
        reply, sources = await _answer_intervention(db, class_id)
    else:
        reply, sources = await _answer_overview(db, class_id)

    return f"{reply}\n\n{DISCLAIMER_NOTE_FA}", intent, sources, created


async def chat(
    db: AsyncSession,
    class_id: int,
    actor_user_id: int,
    message: str,
    conversation_id: int | None,
) -> dict:
    """حلقه کامل گفت‌وگو: ثبت پیام‌ها + پاسخ ریشه‌دار با منابع."""
    conv = (
        await db.get(TeacherCopilotConversation, conversation_id) if conversation_id else None
    )
    if conv is None or conv.class_id != class_id:
        conv = TeacherCopilotConversation(
            class_id=class_id, user_id=actor_user_id, title=message[:80]
        )
        db.add(conv)
        await db.flush()

    db.add(TeacherCopilotMessage(conversation_id=conv.id, role="user", content=message))
    reply, intent, sources, created = await answer(db, class_id, message)
    db.add(
        TeacherCopilotMessage(
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
        "suggestions": [s.id for s in created],
        "model_tier": assistant.pick_tier(message),
        "note_fa": DISCLAIMER_NOTE_FA,
    }


async def list_conversations(db: AsyncSession, class_id: int) -> list[dict]:
    rows = (
        (
            await db.execute(
                select(TeacherCopilotConversation)
                .where(TeacherCopilotConversation.class_id == class_id)
                .order_by(TeacherCopilotConversation.id.desc())
            )
        )
        .scalars()
        .all()
    )
    return [{"id": c.id, "title": c.title, "created_at": c.created_at} for c in rows]


async def conversation_messages(
    db: AsyncSession, class_id: int, conversation_id: int
) -> dict | None:
    conv = await db.get(TeacherCopilotConversation, conversation_id)
    if conv is None or conv.class_id != class_id:
        return None
    msgs = (
        (
            await db.execute(
                select(TeacherCopilotMessage)
                .where(TeacherCopilotMessage.conversation_id == conversation_id)
                .order_by(TeacherCopilotMessage.id)
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


# ------------------------- §16 پیشنهاد اقدام و اختیار معلم -------------------------


async def generate_suggestions(db: AsyncSession, class_id: int) -> list[TeacherSuggestion]:
    """پیشنهاد اقدام از داده واقعی کلاس — idempotent تا زمانی که پیشنهاد
    بازِ همان عنوان وجود دارد."""
    existing = {
        s.title_fa
        for s in (
            await db.execute(
                select(TeacherSuggestion).where(
                    TeacherSuggestion.class_id == class_id,
                    TeacherSuggestion.status == "proposed",
                )
            )
        ).scalars()
    }
    created: list[TeacherSuggestion] = []

    def _add(sugg: TeacherSuggestion) -> None:
        if sugg.title_fa in existing:
            return
        created.append(sugg)
        existing.add(sugg.title_fa)

    radar = await teacher_svc.class_radar(db, class_id)
    groups = await teacher_svc.need_groups(db, class_id)

    # ۱) پیش‌نویس آزمون برای ضعیف‌ترین مبحث دارای خطا/ضعف
    weak = [r for r in radar["rows"] if r["weak_count"]]
    if weak:
        t = weak[0]
        _add(
            TeacherSuggestion(
                class_id=class_id,
                kind="draft_exam",
                title_fa=f"ساخت پیش‌نویس آزمون برای «{t['title']}»",
                evidence_fa=(
                    f"«{t['title']}» با میانگین تسط {fa_num(t['avg_mastery'])}٪ و "
                    f"{fa_num(t['weak_count'])} دانش‌آموز زیر آستانه؛ ضعیف‌ترین مبحث کلاس."
                ),
                actions_fa=[
                    "تأیید — ساخت پیش‌نویس آزمون تشخیصی/کلاسی",
                    "ویرایش — تغییر هدف پیش از ساخت",
                    "رد — بدون ساخت",
                ],
                payload={
                    "goal": f"آزمون پایشی {t['title']}",
                    "exam_type": "class_exam",
                    "topic_id": t["topic_id"],
                },
                status="proposed",
            )
        )

    # ۲) بسته ترمیمی برای گروه مداخله
    inter = next((g for g in groups["groups"] if g["need"] == "intervention"), None)
    if inter is not None and inter["students"]:
        _add(
            TeacherSuggestion(
                class_id=class_id,
                kind="send_practice",
                title_fa=f"ارسال بسته ترمیمی برای {fa_num(len(inter['students']))} دانش‌آموز",
                evidence_fa=(
                    f"{fa_num(len(inter['students']))} دانش‌آموز در گروه «مداخله آموزشی» "
                    f"({', '.join(s['full_name'] for s in inter['students'][:3])}): {inter['action']}."
                ),
                actions_fa=[
                    "تأیید — ایجاد کار «بسته ترمینی» در برنامه دانش‌آموزان فردا",
                    "ویرایش — تغییر نوع کار یا فهرست دانش‌آموزان",
                    "رد — بدون ارسال",
                ],
                payload={
                    "task_type": "remedial_pack",
                    "user_ids": [s["student_id"] for s in inter["students"]],
                },
                status="proposed",
            )
        )

    # ۳) مرور فاصله‌دار برای گروه افت ماندگاری
    ret = next((g for g in groups["groups"] if g["need"] == "retention_drop"), None)
    if ret is not None and ret["students"]:
        _add(
            TeacherSuggestion(
                class_id=class_id,
                kind="send_practice",
                title_fa=f"ارسال مرور فاصله‌دار برای {fa_num(len(ret['students']))} دانش‌آموز",
                evidence_fa=(
                    f"{fa_num(len(ret['students']))} دانش‌آموز نمره قابل قبول ولی افت ماندگاری دارند "
                    f"({', '.join(s['full_name'] for s in ret['students'][:3])}): {ret['action']}."
                ),
                actions_fa=[
                    "تأیید — ایجاد کار «مرور فاصله‌دار» در برنامه دانش‌آموزان فردا",
                    "ویرایش — تغییر نوع کار یا فهرست دانش‌آموزان",
                    "رد — بدون ارسال",
                ],
                payload={
                    "task_type": "spaced_review",
                    "user_ids": [s["student_id"] for s in ret["students"]],
                },
                status="proposed",
            )
        )

    if created:
        db.add_all(created)
        await db.flush()
    return created


async def _execute_draft_exam(
    db: AsyncSession, sugg: TeacherSuggestion, actor_user_id: int
) -> dict:
    """تأیید کارت «ساخت آزمون» → پیش‌نویس آزمون با بلوپرینت واقعی (§8/§16)."""
    cls = await db.get(ClassRoom, sugg.class_id)
    if cls is None:
        raise ValueError("کلاس پیشنهاد یافت نشد")
    payload = sugg.payload or {}
    goal = str(payload.get("goal") or sugg.title_fa)
    exam_type = payload.get("exam_type") if payload.get("exam_type") in eb_svc.EXAM_TYPE_KEYS else "class_exam"
    subject = await _class_subject(db, cls)
    if not subject:
        raise ValueError("درس کلاس مشخص نیست؛ پیش از ساخت آزمون درس را ثبت کنید")

    exam = Exam(
        title_fa=(payload.get("title") or goal)[:200],
        exam_type=exam_type,
        grade=cls.grade,
        subject=subject,
        scope="class",
        school_id=cls.school_id,
        class_id=cls.id,
        status="draft",
        created_by=actor_user_id,
    )
    db.add(exam)
    await db.flush()
    db.add(ExamBuilderProfile(exam_id=exam.id, mode="standard", goal=goal))

    proposal = await eb_svc.propose_blueprint(
        db,
        goal=goal,
        exam_type=exam_type,
        topic_id=payload.get("topic_id"),
        grade=cls.grade,
        subject=subject,
    )
    if proposal.get("ok"):
        exam.blueprint = [
            {
                "topic_id": r["topic_id"],
                "item_kind": r["item_kind"],
                "count": r["count"],
                "diagnostic_purpose": r["diagnostic_purpose"],
            }
            for r in proposal["rows"]
        ]
    await db.flush()
    return {"exam_id": exam.id, "blueprint_ok": bool(proposal.get("ok"))}


async def _execute_send_practice(
    db: AsyncSession, sugg: TeacherSuggestion, actor_user_id: int
) -> dict:
    """تأیید کارت «ارسال تمرین» → ایجاد کار برنامه برای دانش‌آموزان هدف."""
    payload = sugg.payload or {}
    task_type = payload.get("task_type")
    if task_type not in ("lesson", "practice", "remedial_pack", "spaced_review", "retest", "quiz", "cumulative_prep"):
        raise ValueError("نوع کار برنامه نامعتبر است")
    user_ids = [int(u) for u in (payload.get("user_ids") or [])]
    if not user_ids:
        raise ValueError("فهرست دانش‌آموزان پیشنهاد خالی است")

    tomorrow = datetime.now(timezone.utc).date() + timedelta(days=1)
    tasks = [
        PlanTask(
            student_user_id=uid,
            topic_id=payload.get("topic_id"),
            task_type=task_type,
            payload={
                "origin": "teacher_copilot",
                "suggestion_id": sugg.id,
                "note": sugg.title_fa,
                "created_by": actor_user_id,
            },
            for_date=tomorrow,
        )
        for uid in user_ids
    ]
    db.add_all(tasks)
    await db.flush()
    return {"task_ids": [t.id for t in tasks], "students": len(tasks)}


async def decide_suggestion(
    db: AsyncSession,
    class_id: int,
    suggestion_id: int,
    actor_user_id: int,
    action: str,
    edited_actions: list[str] | None = None,
    note: str | None = None,
) -> TeacherSuggestion | None:
    """تأیید/ویرایش/رد پیشنهاد (§16). خارج از کلاس → None (مجری 404);
    تصمیم تکراری یا اجرای ناموفق → ValueError (مجری 409).

    تأیید، اجرای واقعی را در همان تراکنش انجام می‌دهد: ساخت پیش‌نویس
    آزمون یا ایجاد کارهای برنامه — پیش از این، هیچ چیزی اجرا نشده است."""
    sugg = (
        (
            await db.execute(
                select(TeacherSuggestion).where(
                    TeacherSuggestion.id == suggestion_id,
                    TeacherSuggestion.class_id == class_id,
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

    result: dict | None = None
    if action == "approve":
        if sugg.kind == "draft_exam":
            try:
                result = await _execute_draft_exam(db, sugg, actor_user_id)
            except ValueError:
                raise
            except Exception as exc:  # شکست اجرا → 409، وضعیت پیشنهاد دست‌نخورده
                raise ValueError(f"ساخت آزمون ناموفق بود: {exc}") from exc
        elif sugg.kind == "send_practice":
            try:
                result = await _execute_send_practice(db, sugg, actor_user_id)
            except ValueError:
                raise
            except Exception as exc:
                raise ValueError(f"ایجاد کار برنامه ناموفق بود: {exc}") from exc
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

    sugg.result = result
    sugg.decided_by = actor_user_id
    sugg.decided_at = datetime.now(timezone.utc)
    sugg.decision_note = note
    await db.flush()
    return sugg
