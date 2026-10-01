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
}


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


async def compose_answer(
    db: AsyncSession, student_user_id: int, query: str, sources: list[dict], matched_topics: list[Topic]
) -> str:
    """پاسخ شخصی‌سازی‌شده از منابع بازیابی‌شده + خطاهای باز دانش‌آموز."""
    lines: list[str] = []
    if matched_topics:
        lines.append("بر اساس کاتالوگ درس، این مباحث پیدا شدند:")
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
                    f"• «{t.title_fa}» — وضعیت شما: {status_of(st.effective_mastery, st.evidence_count)} "
                    f"(تسلط {round(st.effective_mastery)}٪، ماندگاری {round(st.retention * 100)}٪)"
                )
            else:
                lines.append(f"• «{t.title_fa}» — هنوز شواهدی از شما ثبت نشده است.")
    else:
        lines.append("مبحث منطبقی در کاتالوگ پیدا نشد؛ سؤال را با عنوان فصل یا مبحث بنویس (مثلاً «تعداد زیرمجموعه‌ها»).")

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

    ladder = review_ladder()
    lines.append(f"\nبرنامه مرور پیشنهادی (نردبان {', '.join(map(str, ladder))} روز): مرور بعدی را طبق آزمون بعدی زمان‌بندی کن.")
    lines.append("⚠️ پاسخ از روی منابع کاتالوگ و وضعیت خودتان ساخته شده؛ جایگزین کتاب درسی نیست.")
    return "\n".join(lines)


async def chat(db: AsyncSession, student_user_id: int, message: str, conversation_id: int | None) -> dict:
    """حلقه کامل چت: کش → بازیابی → پاسخ → ثبت پیام."""
    norm = normalize_query(message)
    tier = pick_tier(message)

    conv = await db.get(AiConversation, conversation_id) if conversation_id else None
    if conv is None or conv.student_user_id != student_user_id:
        conv = AiConversation(student_user_id=student_user_id, title=message[:80])
        db.add(conv)
        await db.flush()

    db.add(AiMessage(conversation_id=conv.id, role="user", content=message))

    cached = await semantic_lookup(db, norm)
    if cached is not None:
        reply, cached_flag, sources = cached.response, True, []
        tier_used = "small"
    else:
        sources, matched = await retrieve(db, student_user_id, message)
        reply = await compose_answer(db, student_user_id, message, sources, matched)
        cached_flag = False
        tier_used = tier
        db.add(
            SemanticCache(query_norm=norm, query_original=message, response=reply, hit_count=0)
        )

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
