"""AI assistant (roadmap phase 6 «دستیار هوشمند») — three-layer architecture:
1) کش معنایی: نرمال‌سازی پرسش + شباهت Jaccard → پاسخ تکراری بدون مدل
2) بازیابی (RAG سبک): نگاشت پرسش روی کاتالوگ (مبحث/مهارت/سؤال) + وضعیت SLM خود دانش‌آموز
3) مسیریابی مدل: پرسش ساده → tier=small؛ تحلیلی/بلند → tier=large

پاسخ‌ها همیشه «شفاف»‌اند: منابع بازیابی‌شده برمی‌گردند تا رابط نشان دهد
پاسخ از کجا آمده (اسند: ادعای بی‌منبع ممنوع)."""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.models.assistant import AiConversation, AiMessage, SemanticCache
from app.models.catalog import Skill, Topic
from app.models.slm import ErrorRecord, StudentTopicState
from app.services.slm import review_ladder, status_of

# نرمال‌سازی متن فارسی/عربی برای کش معنایی
_ARABIC_YEH = "\u064a"
_ARABIC_KAF = "\u0643"
_PERSIAN_YEH = "\u06cc"
_PERSIAN_KAF = "\u06a9"
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

CAUSE_HINT_FA = {
    "conceptual": "یک بار مفهوم را از فصل مربوط بخوان و ۲ سؤال تمرینی بزن؛ اگر باز هم اشتباه کردی، تدریس مجدد لازم است.",
    "prerequisite": "اول پیش‌نیاز این مبحث را مرور کن (درخت تسلط را ببین)، بعد برگرد سراغ این سؤال.",
    "calculation": "تمرین محاسباتی کوتاه و زمان‌دار بزن؛ مفهوم را داری ولی محاسبه می‌لغزد.",
    "careless": "بعد از هر حل، ۱۰ ثانیه پاسخ را بازبینی کن؛ الگوی بی‌دقتی تکراری است.",
    "time_management": "سه سؤال را با زمان‌بندی سخت حل کن تا سرعت تصمیم‌گیری بالا برود.",
    "guess": "پاسخ حدسی را علامت زده‌ای — منبع یادگیری واقعی نیست؛ همین مبحث را دوباره تمرین کن.",
    "unclear": "علت این خطا هنوز روشن نیست؛ در دفترچهٔ خطا یکی از شش گزینه را انتخاب کن تا برنامهٔ ترمیم دقیق شود.",
}

# ------------------------- کنترل مقدار و سکوت در آزمون (§9.2 / §9.3) -------------------------
# «سقف پرسش روزانه برای هر دانش‌آموز» — ضمیمه: ۳۰ پرسش در روز (§3.6 هم همین را می‌گوید).
DAILY_QUESTION_CAP = 30
# «در طول هر آزمون رسمی یا خودسنجی زمان‌دار، دستیار خاموش است» (§9.2)
SILENCE_HOURS = 6  # حداکثر مدتِ سکوت برای یک تلاش نیمه‌تمام (جلوگیری از سکوت دائمیِ تلاش رهاشده)


class ChatBlocked(Exception):
    """پرسش مسدودشده: سقف روزانه پر یا دستیار در حین آزمون خاموش است."""

    def __init__(self, message_fa: str, code: str = "blocked", status: int = 403):
        super().__init__(message_fa)
        self.message_fa = message_fa
        self.code = code
        self.status = status


async def daily_usage(db: AsyncSession, student_user_id: int) -> dict:
    """مصرف پرسش‌های امروز (تعداد پیام‌های کاربر از نیمه‌شب تاکنون)."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    count = (
        await db.execute(
            select(AiMessage)
            .join(AiConversation, AiConversation.id == AiMessage.conversation_id)
            .where(
                AiConversation.student_user_id == student_user_id,
                AiMessage.role == "user",
                AiMessage.created_at >= midnight,
            )
        )
    ).scalars().all()
    used = len(count)
    cap = DAILY_QUESTION_CAP
    return {
        "used": used,
        "cap": cap,
        "remaining": max(0, cap - used),
        "limit_reached": used >= cap,
        "message_fa": (
            f"سقف پرسش روزانهٔ دستیار ({fa_num(cap)} پرسش) پر شد؛ فردا دوباره بپرس "
            "یا تا آن‌وقت از درس‌نامه، تمرین پله‌ای و دفترچهٔ خطا کمک بگیر (§9.3)."
        ),
    }


async def exam_silence(db: AsyncSession, student_user_id: int) -> dict:
    """سکوت خودکار حین آزمون (§9.2): تلاش نیمه‌تمامی که بازهٔ آزمونش باز است
    و در چند ساعت اخیر شروع شده ⇒ دستیار خاموش."""
    from datetime import timedelta

    from app.models.assessment import Exam, ExamAttempt

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    attempts = (
        await db.execute(
            select(ExamAttempt)
            .join(Exam, Exam.id == ExamAttempt.exam_id)
            .where(
                ExamAttempt.student_user_id == student_user_id,
                ExamAttempt.status == "in_progress",
            )
            .options(selectinload(ExamAttempt.exam))
        )
    ).scalars().all()
    for a in attempts:
        exam = a.exam
        if exam is None:
            continue
        started = a.started_at.replace(tzinfo=None) if a.started_at else now
        opens = exam.opens_at.replace(tzinfo=None) if exam.opens_at else None
        closes = exam.closes_at.replace(tzinfo=None) if exam.closes_at else None
        window_open = (opens is None or opens <= now) and (closes is None or now <= closes)
        fresh = (now - started) <= timedelta(hours=SILENCE_HOURS)
        if window_open and fresh:
            return {
                "silenced": True,
                "exam_id": exam.id,
                "exam_title": exam.title_fa,
                "message_fa": (
                    f"دستیار در حین آزمون («{exam.title_fa}») خاموش است تا دسترسی یکسان بماند "
                    "(§9.2)؛ پس از ثبت آزمون می‌توانی بپرسی."
                ),
            }
    return {"silenced": False, "exam_id": None, "exam_title": None, "message_fa": None}


async def chat_status(db: AsyncSession, student_user_id: int) -> dict:
    """وضعیت چت: سقف روزانه + سکوت آزمون — برای نمایش در رابط دستیار."""
    usage = await daily_usage(db, student_user_id)
    silence = await exam_silence(db, student_user_id)
    blocked = usage["limit_reached"] or silence["silenced"]
    return {
        **usage,
        "silenced": silence["silenced"],
        "silence_exam_title": silence["exam_title"],
        "blocked": blocked,
        "reason_fa": silence["message_fa"] if silence["silenced"] else (usage["message_fa"] if usage["limit_reached"] else None),
        "note_fa": "سقف روزانهٔ پرسش و سکوت حین آزمون (§9.2 / §9.3).",
    }


def fa_num(n) -> str:
    return str(n).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


async def assert_chat_allowed(db: AsyncSession, student_user_id: int) -> dict:
    """قبل از پردازش پرسش: سقف روزانه و سکوت حین آزمون. در صورت مسدودی ChatBlocked."""
    status = await chat_status(db, student_user_id)
    if status["silenced"]:
        raise ChatBlocked(status["reason_fa"], code="exam_silence", status=403)
    if status["limit_reached"]:
        raise ChatBlocked(status["reason_fa"], code="daily_cap", status=429)
    return status


def normalize_query(text: str) -> str:
    """نرمال‌سازی: ی/ک عربی → فارسی، ارقام → لاتین، حذف اعراب/تشریح و
    نشانه‌گذاری (شامل ؟ عربی)، نیم‌فاصله → فاصله، حروف کوچک."""
    t = unicodedata.normalize("NFKC", text or "")
    t = t.replace(_ARABIC_YEH, _PERSIAN_YEH).replace(_ARABIC_KAF, _PERSIAN_KAF)
    t = t.translate(_DIGITS)
    # حذف اعراب (ًٌٍَُِّْ) + خالی‌نویسی + تشدید/ tatweel
    t = re.sub(r"[\u064b-\u065f\u0670\u0640]", "", t)
    # نیم‌فاصله (ZWNJ) → فاصله تا «زیر‌مجموعه» == «زیر مجموعه»
    t = t.replace("\u200c", " ")
    # هر نشانه‌گذاری غیرکلمه‌ای (؟ ، ؛ . ، Latin punct) → فاصله
    t = re.sub(r"[^\w\s]", " ", t, flags=re.UNICODE)
    t = re.sub(r"\s+", " ", t).strip().lower()
    return t


def jaccard(a: str, b: str) -> float:
    sa, sb = set(a.split()), set(b.split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def pick_tier(query: str) -> str:
    """مسیریابی مدل: پرسش کوتاه/کلیشه‌ای → small؛ تحلیلی/بلند → large."""
    q = query.strip()
    analytical = re.search(r"(چرا|مقایسه|دلیل|تحلیل|برنامه|کدام بهتر|تفاوت)", q)
    long_q = len(q.split()) >= 10
    return "large" if analytical or long_q else "small"


async def semantic_lookup(db: AsyncSession, norm: str) -> SemanticCache | None:
    """کش دقیق (نرمال‌شده) + شباهت بالای آستانه روی کل کش (کوچک؛ بعداً ANN)."""
    s = get_settings()
    exact = (
        await db.execute(select(SemanticCache).where(SemanticCache.query_norm == norm))
    ).scalar_one_or_none()
    if exact is not None:
        exact.hit_count += 1
        exact.last_hit_at = datetime.now(timezone.utc)
        return exact
    rows = (await db.execute(select(SemanticCache))).scalars().all()
    best, best_sim = None, 0.0
    for r in rows:
        sim = jaccard(norm, r.query_norm)
        if sim > best_sim:
            best, best_sim = r, sim
    if best is not None and best_sim >= s.assistant_cache_similarity:
        best.hit_count += 1
        best.last_hit_at = datetime.now(timezone.utc)
        return best
    return None


async def retrieve(db: AsyncSession, student_user_id: int, query: str) -> tuple[list[dict], list[Topic]]:
    """RAG سبک: تطابق توکنی روی عناوین مباحث/مهارت‌ها + وضعیت خود دانش‌آموز."""
    s = get_settings()
    tokens = [t for t in normalize_query(query).split() if len(t) >= 3]
    topics = (await db.execute(select(Topic))).scalars().all()
    skills = (await db.execute(select(Skill))).scalars().all()
    states = {
        st.topic_id: st
        for st in (
            await db.execute(select(StudentTopicState).where(StudentTopicState.student_user_id == student_user_id))
        ).scalars()
    }

    scored: list[tuple[float, Topic]] = []
    for t in topics:
        hay = normalize_query(t.title_fa)
        score = sum(1 for tok in tokens if tok in hay)
        if score:
            scored.append((float(score), t))
    matched_skills = [sk for sk in skills if any(tok in normalize_query(sk.title_fa) for tok in tokens)]
    for sk in matched_skills:
        topic = next((t for t in topics if t.id == sk.topic_id), None)
        if topic is not None and all(t.id != topic.id for _, t in scored):
            scored.append((0.5, topic))
    scored.sort(key=lambda x: -x[0])
    top = [t for _, t in scored[: s.assistant_max_sources]]

    sources = [
        {"type": "topic", "id": t.id, "title": t.title_fa, "status": status_of(states[t.id].effective_mastery, states[t.id].evidence_count) if t.id in states else "unknown"}
        for t in top
    ]
    return sources, top


async def personal_block(
    db: AsyncSession, student_user_id: int, matched_topics: list[Topic]
) -> str:
    """بخش شخصی پاسخ — همیشه برای همین کاربر ساخته می‌شود و هرگز کش نمی‌شود
    (حریم خصوصی: وضعیت/خطاهای دانش‌آموز نباید به کاربر دیگری برسد)."""
    lines: list[str] = []
    if matched_topics:
        lines.append("وضعیت شما:")
        states = {
            st.topic_id: st
            for st in (
                await db.execute(select(StudentTopicState).where(StudentTopicState.student_user_id == student_user_id))
            ).scalars()
        }
        for t in matched_topics[:3]:
            st = states.get(t.id)
            if st is not None:
                lines.append(
                    f"• «{t.title_fa}» — {status_of(st.effective_mastery, st.evidence_count)} "
                    f"(تسلط {round(st.effective_mastery)}٪، ماندگاری {round(st.retention * 100)}٪)"
                )
            else:
                lines.append(f"• «{t.title_fa}» — هنوز شواهدی از شما ثبت نشده است.")

    # خطاهای باز → اقدام مشخص
    open_errors = (
        await db.execute(
            select(ErrorRecord).where(
                ErrorRecord.student_user_id == student_user_id,
                ErrorRecord.status.in_(["open", "relapsed"]),
            )
        )
    ).scalars().all()
    if open_errors:
        top = open_errors[0]
        lines.append(
            f"\nخطای باز شما: «{top.item_snapshot.get('body', '')[:80]}» → {CAUSE_HINT_FA.get(top.cause, '')}"
        )

    return "\n".join(lines)


def generic_intro(matched_topics: list[Topic]) -> str:
    """بخش عمومی پاسخ (قابل کش): فقط عنوان مباحث — بدون هیچ داده شخصی."""
    if matched_topics:
        titles = "، ".join(f"«{t.title_fa}»" for t in matched_topics[:3])
        return f"بر اساس کاتالوگ درس، این مباحث پیدا شدند: {titles}"
    return "مبحث منطبقی در کاتالوگ پیدا نشد؛ سؤال را با عنوان فصل یا مبحث بنویس (مثلاً «تعداد زیرمجموعه‌ها»)."


def generic_tail() -> str:
    """بخش عمومی پاسخ (قابل کش): نردبان مرور + هشدار منبع."""
    ladder = review_ladder()
    return (
        f"\nبرنامه مرور پیشنهادی (نردبان {', '.join(map(str, ladder))} روز): "
        "مرور بعدی را طبق آزمون بعدی زمان‌بندی کن.\n"
        "⚠️ پاسخ از روی منابع کاتالوگ و وضعیت خودتان ساخته شده؛ جایگزین کتاب درسی نیست."
    )


def _cache_parts(response: str) -> tuple[str, str] | None:
    """نرمال‌شده قدیمی (حاوی داده شخصی) نباید استفاده شود؛ فقط قالب جدید {intro} || {tail}."""
    if " || " not in response:
        return None
    intro, tail = response.split(" || ", 1)
    return intro, tail


async def chat(db: AsyncSession, student_user_id: int, message: str, conversation_id: int | None) -> dict:
    """حلقه کامل چت: بازیابی همیشه تازه → کش فقط بخش عمومی → الحاق بخش شخصی
    همین کاربر → ثبت پیام (بخش شخصی هرگز وارد کش نمی‌شود)."""
    norm = normalize_query(message)
    tier = pick_tier(message)

    conv = await db.get(AiConversation, conversation_id) if conversation_id else None
    if conv is None or conv.student_user_id != student_user_id:
        conv = AiConversation(student_user_id=student_user_id, title=message[:80])
        db.add(conv)
        await db.flush()

    db.add(AiMessage(conversation_id=conv.id, role="user", content=message))

    # بازیابی منابع در هر دو مسیر (کش/بدون کش) تا منابع همیشه برگردند
    sources, matched = await retrieve(db, student_user_id, message)

    cached = await semantic_lookup(db, norm)
    parts = _cache_parts(cached.response) if cached is not None else None
    if parts is not None:
        intro, tail = parts
        cached_flag, tier_used = True, "small"
    else:
        intro = generic_intro(matched)
        tail = generic_tail()
        cached_flag, tier_used = False, tier
        if cached is not None:
            # رکورد قدیمی با پاسخ کامل (حاوی داده شخصی) → بازنویسی به قالب عمومی
            cached.response = f"{intro} || {tail}"
        else:
            db.add(
                SemanticCache(
                    query_norm=norm,
                    query_original=message,
                    response=f"{intro} || {tail}",
                    hit_count=0,
                )
            )

    personal = await personal_block(db, student_user_id, matched)
    reply = "\n\n".join(p for p in (intro, personal, tail) if p)

    db.add(
        AiMessage(
            conversation_id=conv.id,
            role="assistant",
            content=reply,
            model_tier=tier_used,
            sources=sources or None,
            cached=1 if cached_flag else 0,
        )
    )
    await db.flush()
    return {
        "conversation_id": conv.id,
        "reply": reply,
        "sources": sources,
        "model_tier": tier_used,
        "cached": cached_flag,
    }
