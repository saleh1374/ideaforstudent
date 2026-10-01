"""سازندهٔ آزمون معلم و تحلیل پس از آزمون (سند پنل معلم §8 و §10).

پیشنهاد بلوپرینت «قوانین‌محور و قطعی» است (بدون سرویس هوش مصنوعی بیرونی):
متن هدف معلم روی مباحث کاتالوگ تطبیق داده می‌شود، پیش‌نیازهای مبحث هدف از
گراف `Prerequisite` خوانده می‌شود و ردیف‌های بلوپرینت — {مبحث، نوع سؤال،
تعداد، هدف تشخیصی} — با توضیح فارسی ساخته می‌شوند (§8.2، شکل ۹).

تشخیص خودکار «سؤال بد» (§10.2) با آستانه‌های صریحِ `THRESHOLDS` انجام
می‌شود؛ چون app/core/config.py بین چند تیم مشترک است و خارج از محدودهٔ این
تیم است، آستانه‌های این ماژول همین‌جا به‌صورت ثابتِ قابل‌تنظیم تعریف
شده‌اند (قدرت تفکیک ۰٫۱۵، اختلاف دشواری ۰٫۳، z زمان ۲٫۵ — دقیقاً متن §10.2).

یادداشت‌های عمدیِ حذف‌شده از دامنه:
- «اختلاف فرم‌های موازی» (variance(form_scores)) — ساختار فرم موازی هنوز در
  مدل‌ها وجود ندارد؛ با نبود داده به‌جای محاسبهٔ نادرست، نادیده گرفته می‌شود.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from statistics import fmean, pstdev

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.assessment import AttemptAnswer, Exam, ExamAttempt, ExamItem, QuestionItem
from app.models.catalog import Book, Chapter, Prerequisite, Topic
from app.models.exam_builder import ItemAnalysis

# ------------------------- برچسب‌های فارسی (اینجا، محلی) -------------------------

EXAM_TYPES_FA: dict[str, str] = {
    "class_exam": "آزمون کلاسی",
    "quiz": "آزمونک",
    "remedial": "آزمون ترمیمی",
    "prerequisite": "آزمون پیش‌نیاز",
    "diagnostic": "آزمون تشخیصی",
}
EXAM_TYPE_KEYS = tuple(EXAM_TYPES_FA)

MODES_FA: dict[str, str] = {
    "standard": "استاندارد (ورود به برد)",
    "personal_diagnostic": "تشخیصی شخصی (فقط SLM — بدون برد)",
}
MODE_KEYS = tuple(MODES_FA)

ITEM_KINDS_FA: dict[str, str] = {
    "concept_base": "مفهوم پایه",
    "prerequisite_skill": "مهارت پیش‌نیاز",
    "direct_application": "کاربرد مستقیم",
    "reasoning": "استدلال و کاربرد ترکیبی",
}
ITEM_KIND_KEYS = tuple(ITEM_KINDS_FA)

# شش‌علت خطای سند دانش‌آموز §6 — نسخهٔ محلی (frontend/src/lib/labels.ts مشترک نیست)
CAUSE_FA: dict[str, str] = {
    "conceptual": "ضعف مفهومی",
    "prerequisite": "ضعف پیش‌نیاز",
    "calculation": "خطای محاسباتی",
    "careless": "بی‌دقتی",
    "time_management": "کمبود زمان",
    "guess": "حدس",
}
OPTION_FA: dict[str, str] = {"A": "الف", "B": "ب", "C": "ج", "D": "د"}


@dataclass(frozen=True)
class AnalysisThresholds:
    """آستانه‌های §10.2 — پرچم «نیازمند بازبینی»."""

    discrimination_min: float = 0.15     # قدرت تفکیک زیر این مقدار ⇒ سؤال بد
    difficulty_gap: float = 0.30         # |d تجربی − d پیش‌فرض| بیش از این ⇒ بازبینی
    time_zscore_max: float = 2.5         # z-score زمان پاسخ (در صورت دادهٔ زمانی)
    min_attempts_discrimination: int = 4  # زیر این تعداد تلاش، تفکیک قابل محاسبه نیست
    min_items_for_time_z: int = 4        # برای z زمان به مقایسهٔ چند سؤال نیاز است
    # دشواری پیش‌فرض هر سؤال (d پیش‌فرضِ ستون difficulty بانک سؤال)
    prior_by_difficulty: dict[str, float] = field(
        default_factory=lambda: {"easy": 0.85, "medium": 0.60, "hard": 0.35}
    )

    def prior_of(self, difficulty: str | None) -> float:
        return self.prior_by_difficulty.get(difficulty or "medium", 0.60)


THRESHOLDS = AnalysisThresholds()


# ------------------------------ ابزار متن فارسی ------------------------------

_ARABIC_YEH = str.maketrans({"ي": "ی", "ى": "ی", "ئ": "ی", "ك": "ک", "أ": "ا", "إ": "ا", "ٱ": "ا", "ة": "ه", "ۀ": "ه"})
_DIACRITICS = re.compile(r"[ً-ْـٰ]")
_TOKEN = re.compile(r"[0-9a-zA-Z؀-ۿ]+")


def normalize_fa(text: str | None) -> str:
    """نرمال‌سازی متن فارسی برای تطبیق کلمه‌ای: ي→ی، ك→ک، همزه/تشریح،
    حذف اعراب و نیم‌فاصله → فاصله، کوچک‌کردن."""
    s = text or ""
    s = s.translate(_ARABIC_YEH)
    s = _DIACRITICS.sub("", s)
    s = s.replace("\u200c", " ")
    return s.lower().strip()


def fa_digits(value: float | int | None, digits: int = 0) -> str:
    """نمایش عدد با ارقام فارسی در متن‌های خودکار."""
    if value is None:
        return "—"
    if isinstance(value, float):
        text = f"{value:.{digits}f}"
    else:
        text = str(value)
    return text.translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


# --------------------------- بانک سؤال / بلوپرینت ---------------------------


async def active_item_counts(db: AsyncSession, topic_ids: list[int]) -> dict[int, int]:
    """تعداد سؤال‌های فعالِ بانک برای هر مبحث (برای نمایش «در دسترس»)."""
    if not topic_ids:
        return {}
    rows = (
        await db.execute(
            select(QuestionItem.topic_id)
            .where(QuestionItem.topic_id.in_(topic_ids), QuestionItem.is_active == 1)
        )
    ).scalars().all()
    counts: Counter[int] = Counter(rows)
    return {tid: counts.get(tid, 0) for tid in topic_ids}


async def decorate_blueprint(db: AsyncSession, rows: list[dict]) -> list[dict]:
    """افزودن عنوان مبحث و تعداد سؤال در دسترس به ردیف‌های ذخیره‌شده."""
    ids = [r.get("topic_id") for r in rows if r.get("topic_id")]
    titles = {
        t.id: t.title_fa
        for t in (await db.execute(select(Topic).where(Topic.id.in_(ids)))).scalars()
    } if ids else {}
    available = await active_item_counts(db, ids)
    out = []
    for r in rows:
        tid = r.get("topic_id")
        out.append({**r, "topic_title": titles.get(tid, "—"), "available": available.get(tid, 0)})
    return out


def validate_blueprint(rows: list[dict]) -> list[dict]:
    """اعتبارسنجی ردیف‌های بلوپرینت ویرایش‌شده توسط معلم (خطا: ValueError با پیام فارسی)."""
    out: list[dict] = []
    for r in rows:
        try:
            topic_id = int(r.get("topic_id"))
            count = int(r.get("count"))
        except (TypeError, ValueError):
            raise ValueError("ردیف بلوپرینت نامعتبر است؛ شماره مبحث و تعداد باید عدد باشند") from None
        if not 1 <= count <= 20:
            raise ValueError("تعداد سؤال هر ردیف بلوپرینت باید بین ۱ تا ۲۰ باشد")
        kind = r.get("item_kind") or "concept_base"
        if kind not in ITEM_KIND_KEYS:
            raise ValueError("نوع سؤال در بلوپرینت نامعتبر است")
        out.append(
            {
                "topic_id": topic_id,
                "item_kind": kind,
                "count": count,
                "diagnostic_purpose": str(r.get("diagnostic_purpose") or ""),
            }
        )
    return out


def _counts_for(exam_type: str | None) -> dict[str, int]:
    """تعداد هر نوع سؤال به تفکیک نوع آزمون (§8.1 + شکل ۹ §8.2):
    آزمون تشخیصی ۸سؤالیِ §8.5، آزمونک کوتاه و کم‌ریسک (§8.1)."""
    if exam_type == "quiz":
        return {"concept_base": 2, "prerequisite_skill": 1, "direct_application": 1, "reasoning": 1}
    if exam_type == "prerequisite":
        return {"concept_base": 2, "prerequisite_skill": 2, "direct_application": 1, "reasoning": 0}
    if exam_type == "remedial":
        return {"concept_base": 2, "prerequisite_skill": 1, "direct_application": 2, "reasoning": 1}
    if exam_type == "diagnostic":
        return {"concept_base": 3, "prerequisite_skill": 2, "direct_application": 2, "reasoning": 1}
    # class_exam (پیش‌فرض رسمی) و سایر انواع
    return {"concept_base": 3, "prerequisite_skill": 2, "direct_application": 2, "reasoning": 2}


def _score_topic(title: str, tokens: list[str]) -> int:
    t = normalize_fa(title)
    score = 0
    for tok in tokens:
        if len(tok) < 3:
            continue
        if tok in t:
            score += len(tok) if tok in t.split() else max(2, len(tok) // 2)
    return score


async def propose_blueprint(
    db: AsyncSession,
    *,
    goal: str,
    exam_type: str | None,
    topic_id: int | None = None,
    grade: str | None = None,
    subject: str | None = None,
) -> dict:
    """§8.2: از هدفِ متنیِ معلم به ردیف‌های بلوپرینت — قطعی و قوانین‌محور.

    ترتیب ردیف‌ها مطابق شکل ۹: مفهوم پایه ← پیش‌نیازها ← کاربرد مستقیم ←
    استدلال/کاربرد ترکیبی.
    """
    # ---- کاندیداهای مبحث (با فیلتر پایه/درس در صورت امکان) ----
    rows = (
        await db.execute(
            select(Topic, Chapter, Book)
            .join(Chapter, Topic.chapter_id == Chapter.id)
            .join(Book, Chapter.book_id == Book.id)
        )
    ).all()
    if not rows:
        return {"ok": False, "reason": "کاتالوگ مبحثی ثبت نشده است؛ ابتدا کتاب‌ها و مباحث را بارگذاری کنید."}

    candidates = [(tp, bk) for tp, _ch, bk in rows]
    scoped = [
        (tp, bk)
        for tp, bk in candidates
        if (grade is None or bk.grade == grade) and (subject is None or bk.subject == subject)
    ]
    pool = scoped or candidates

    # ---- تعیین مبحث هدف: topic_id صریح ← تطبیق کلمه‌ای هدف ← اولین مبحث پایه ----
    target: Topic | None = None
    if topic_id is not None:
        target = next((tp for tp, _bk in pool if tp.id == topic_id), None)
        if target is None:
            target = next((tp for tp, _bk in candidates if tp.id == topic_id), None)
    if target is None:
        tokens = [normalize_fa(t) for t in _TOKEN.findall(goal)]
        best_score, best = 0, None
        for tp, _bk in pool:
            s = _score_topic(tp.title_fa, tokens)
            if s > best_score:
                best_score, best = s, tp
        if best is not None and best_score >= 4:
            target = best
    if target is None:
        target = sorted(pool, key=lambda tp: (tp.chapter_id, tp.order, tp.id))[0][0]
    if target is None:
        return {"ok": False, "reason": "مبحثی برای ساخت بلوپرینت پیدا نشد."}

    # ---- پیش‌نیازهای مبحث هدف (گراف جهت‌دار catalog.Prerequisite) ----
    prereq_ids = (
        await db.execute(select(Prerequisite.prereq_topic_id).where(Prerequisite.topic_id == target.id))
    ).scalars().all()
    prereq_topics = []
    if prereq_ids:
        found = (await db.execute(select(Topic).where(Topic.id.in_(prereq_ids)))).scalars().all()
        by_id = {t.id: t for t in found}
        prereq_topics = [by_id[i] for i in sorted(prereq_ids) if i in by_id]

    counts = _counts_for(exam_type)
    spec_rows: list[dict] = []

    def add(tp: Topic, kind: str, count: int, purpose: str) -> None:
        if count > 0:
            spec_rows.append(
                {
                    "topic_id": tp.id,
                    "item_kind": kind,
                    "count": count,
                    "diagnostic_purpose": purpose,
                }
            )

    add(target, "concept_base", counts["concept_base"], "سنجش درک مفهوم پیش از کاربرد")
    for p in prereq_topics:
        add(
            p,
            "prerequisite_skill",
            counts["prerequisite_skill"],
            f"رد کردن احتمال ضعف پیش‌نیاز «{p.title_fa}»",
        )
    add(target, "direct_application", counts["direct_application"], "سنجش خودِ مبحث هدف")
    add(target, "reasoning", counts["reasoning"], "تفکیک ضعف مفهومی از ضعف کاربردی")

    decorated = await decorate_blueprint(db, spec_rows)
    total = sum(r["count"] for r in decorated)
    summary = (
        f"برای هدف «{goal.strip()}» {fa_digits(len(decorated))} ردیف بلوپرینت با مجموع "
        f"{fa_digits(total)} سؤال پیشنهاد شد؛ مبحث هدف: «{target.title_fa}»"
        + (f" با {fa_digits(len(prereq_topics))} پیش‌نیاز." if prereq_topics else ".")
    )
    return {
        "ok": True,
        "goal": goal.strip(),
        "target_topic": {"topic_id": target.id, "title": target.title_fa},
        "rows": decorated,
        "summary_fa": summary,
    }


async def assemble_from_blueprint(db: AsyncSession, exam: Exam) -> dict:
    """اتصال سؤال‌های بانک به آزمون، ردیف‌به‌ردیف از روی بلوپرینت (§8.2).
    کسریِ بانک پاسخ نرم می‌دهد: {ok: false, reason} با همان سؤال‌هایی که
    پیدا شده‌اند متصل می‌شوند."""
    rows = exam.blueprint or []
    if not rows:
        return {"ok": False, "reason": "هنوز بلوپرینتی ثبت نشده است؛ ابتدا هدف آزمون را بنویسید.", "attached": 0}
    rows = await decorate_blueprint(db, rows)

    attached_ids = {
        iid
        for iid in (
            await db.execute(select(ExamItem.item_id).where(ExamItem.exam_id == exam.id))
        ).scalars()
    }
    order_vals = (
        await db.execute(select(ExamItem.order).where(ExamItem.exam_id == exam.id))
    ).scalars().all()
    next_order = max(order_vals) + 1 if order_vals else 1

    used_per_topic: Counter[int] = Counter()
    for iid in attached_ids:
        q = await db.get(QuestionItem, iid)
        if q is not None:
            used_per_topic[q.topic_id] += 1

    attached = 0
    shortfalls: list[str] = []
    for row in rows:
        tid = row.get("topic_id")
        need = int(row.get("count") or 0) - used_per_topic.get(tid, 0)
        if need <= 0:
            continue
        pool = select(QuestionItem).where(
            QuestionItem.topic_id == tid,
            QuestionItem.is_active == 1,
        )
        if attached_ids:
            pool = pool.where(QuestionItem.id.not_in(tuple(attached_ids)))
        picks = (
            await db.execute(pool.order_by(QuestionItem.difficulty_weight, QuestionItem.id).limit(need))
        ).scalars().all()
        for q in picks:
            db.add(ExamItem(exam_id=exam.id, item_id=q.id, order=next_order, points=1.0))
            attached_ids.add(q.id)
            used_per_topic[tid] += 1
            next_order += 1
            attached += 1
        if len(picks) < need:
            title = row.get("topic_title") or f"مبحث {tid}"
            shortfalls.append(f"«{title}»: {fa_digits(need - len(picks))} سؤال کم")

    await db.flush()
    if attached == 0 and shortfalls:
        return {
            "ok": False,
            "attached": 0,
            "reason": "هیچ سؤال فعالِ جدیدی برای این بلوپرینت در بانک نیست — سؤال دستی اضافه کنید. کسری: "
            + "؛ ".join(shortfalls),
        }
    if shortfalls:
        return {
            "ok": False,
            "attached": attached,
            "reason": "به‌اندازهٔ بلوپرینت سؤال فعال در بانک نبود؛ سؤال‌های موجود متصل شد. کسری: "
            + "؛ ".join(shortfalls),
        }
    return {"ok": True, "attached": attached, "reason": None}


# ------------------------------ تحلیل پس از آزمون (§10) ------------------------------


def _discrimination(
    correct_by_attempt: dict[int, bool],
    upper_ids: list[int],
    lower_ids: list[int],
) -> float | None:
    """قدرت تفکیک کلاسیک: میانگین درستِ ۲۷٪ بالا منهای ۲۷٪ پایین."""
    if not upper_ids or not lower_ids:
        return None
    p_upper = fmean(1.0 if correct_by_attempt.get(a) else 0.0 for a in upper_ids)
    p_lower = fmean(1.0 if correct_by_attempt.get(a) else 0.0 for a in lower_ids)
    return round(p_upper - p_lower, 2)


def _build_comment(
    *,
    correct_pct: float,
    discrimination: float | None,
    avg_time_ms: int | None,
    top_wrong: str | None,
    top_wrong_pct: float | None,
    misconception: str | None,
    reasons: list[str],
) -> str:
    parts = [f"دشواری تجربی {fa_digits(round(correct_pct))}٪"]
    if discrimination is not None:
        parts.append(f"قدرت تفکیک {fa_digits(discrimination, 2)}")
    else:
        parts.append("قدرت تفکیک قابل محاسبه نیست (تلاش کافی نیست)")
    if avg_time_ms:
        parts.append(f"میانگین زمان پاسخ {fa_digits(round(avg_time_ms / 1000))} ثانیه")
    if top_wrong:
        seg = f"پرتکرارترین گزینهٔ غلط {OPTION_FA.get(top_wrong, top_wrong)}"
        if top_wrong_pct is not None:
            seg += f" ({fa_digits(round(top_wrong_pct))}٪ خطاها)"
        if misconception:
            seg += f" — {misconception}"
        parts.append(seg)
    base = "؛ ".join(parts) + "."
    if reasons:
        return "⚠ " + base + " " + "؛ ".join(reasons) + ". بررسی شود."
    return base


async def compute_item_analysis(db: AsyncSession, exam: Exam) -> dict:
    """§10.1 تحلیل هر سؤال + §10.2 پرچم خودکار «نیازمند بازبینی».
    نتیجه در جدول اختصاصی ItemAnalysis پایدار می‌شود."""
    exam_items = (
        await db.execute(
            select(ExamItem)
            .options(selectinload(ExamItem.item))
            .where(ExamItem.exam_id == exam.id)
            .order_by(ExamItem.order)
        )
    ).scalars().all()

    attempts = (
        await db.execute(
            select(ExamAttempt).where(
                ExamAttempt.exam_id == exam.id,
                ExamAttempt.status.in_(["graded", "submitted"]),
            )
        )
    ).scalars().all()
    attempt_ids = [a.id for a in attempts]

    thresholds_out = {
        "discrimination_min": THRESHOLDS.discrimination_min,
        "difficulty_gap": THRESHOLDS.difficulty_gap,
        "time_zscore_max": THRESHOLDS.time_zscore_max,
    }

    if not exam_items:
        return {
            "ok": True,
            "exam_id": exam.id,
            "attempts": len(attempt_ids),
            "items": [],
            "flagged_count": 0,
            "thresholds": thresholds_out,
            "note_fa": "هنوز سؤالی به آزمون اضافه نشده است.",
        }

    answers = []
    if attempt_ids:
        answers = (
            await db.execute(
                select(AttemptAnswer).where(AttemptAnswer.exam_item_id.in_([ei.id for ei in exam_items]))
            )
        ).scalars().all()

    topic_titles = {
        t.id: t.title_fa
        for t in (
            await db.execute(select(Topic).where(Topic.id.in_([ei.item.topic_id for ei in exam_items])))
        ).scalars()
    } if exam_items else {}

    # ---- امتیاز کل هر تلاش (بدون پاسخ = غلط، مطابق تصحیح خودکار) ----
    total_items = len(exam_items)
    correct_by_attempt: dict[int, dict[int, bool]] = defaultdict(dict)
    for a in answers:
        correct_by_attempt[a.attempt_id][a.exam_item_id] = bool(a.is_correct)
    attempt_score = {
        aid: sum(1 for ok in per.values() if ok) for aid, per in correct_by_attempt.items()
    }

    n_attempts = len(attempt_ids)
    ranked = sorted(attempt_ids, key=lambda aid: -attempt_score.get(aid, 0))  # پایدار برای تساوی
    upper_ids: list[int] = []
    lower_ids: list[int] = []
    if n_attempts >= THRESHOLDS.min_attempts_discrimination:
        k = max(1, round(n_attempts * 0.27))
        upper_ids = ranked[:k]
        lower_ids = ranked[-k:]

    answers_by_item: dict[int, list[AttemptAnswer]] = defaultdict(list)
    for a in answers:
        answers_by_item[a.exam_item_id].append(a)

    # ---- میانگین زمان هر سؤال (برای z-score زمان §10.2) ----
    item_mean_time: dict[int, float] = {}
    for ei in exam_items:
        times = [a.time_spent_ms for a in answers_by_item.get(ei.id, []) if a.time_spent_ms and a.time_spent_ms > 0]
        if times:
            item_mean_time[ei.id] = fmean(times)
    time_z: dict[int, float] = {}
    if len(item_mean_time) >= THRESHOLDS.min_items_for_time_z:
        vals = list(item_mean_time.values())
        sd = pstdev(vals)
        if sd > 0:
            mu = fmean(vals)
            time_z = {eid: (m - mu) / sd for eid, m in item_mean_time.items()}

    # ---- محاسبه و پایدارسازی هر ردیف ----
    existing = {
        row.exam_item_id: row
        for row in (
            await db.execute(select(ItemAnalysis).where(ItemAnalysis.exam_id == exam.id))
        ).scalars()
    }
    for old_id in set(existing) - {ei.id for ei in exam_items}:
        await db.delete(existing[old_id])

    out_rows: list[dict] = []
    flagged_count = 0
    for ei in exam_items:
        q = ei.item
        rows_for_item = answers_by_item.get(ei.id, [])
        correct_count = sum(1 for a in rows_for_item if a.is_correct)
        # پاسخ‌داده‌نشده در جمعیت تلاش‌ها غلط حساب می‌شود (همان قاعدهٔ تصحیح)
        correct_pct = round(100.0 * correct_count / n_attempts, 1) if n_attempts else 0.0
        empirical = round(correct_pct / 100.0, 2)
        prior = THRESHOLDS.prior_of(q.difficulty)

        discrimination = _discrimination(
            {aid: bool(correct_by_attempt.get(aid, {}).get(ei.id)) for aid in attempt_ids},
            upper_ids,
            lower_ids,
        )

        timed = [a.time_spent_ms for a in rows_for_item if a.time_spent_ms and a.time_spent_ms > 0]
        avg_time_ms = int(fmean(timed)) if timed else None

        wrongs = [a for a in rows_for_item if a.selected_option and not a.is_correct]
        top_wrong = None
        top_wrong_pct = None
        misconception = None
        if wrongs:
            counter = Counter(a.selected_option for a in wrongs)
            top_wrong, top_count = counter.most_common(1)[0]
            top_wrong_pct = round(100.0 * top_count / len(wrongs), 1)
            cause = (q.distractor_causes or {}).get(top_wrong)
            cause_fa = CAUSE_FA.get(cause or "")
            if q.misconception:
                misconception = f"{q.misconception} ({cause_fa})" if cause_fa else q.misconception
            elif cause_fa:
                misconception = cause_fa

        reasons: list[str] = []
        if discrimination is not None and discrimination < THRESHOLDS.discrimination_min:
            reasons.append(
                f"قدرت تفکیک {fa_digits(discrimination, 2)} کمتر از آستانه "
                f"{fa_digits(THRESHOLDS.discrimination_min, 2)} است"
            )
        if n_attempts and abs(empirical - prior) > THRESHOLDS.difficulty_gap:
            reasons.append(
                f"اختلاف دشواری تجربی ({fa_digits(empirical, 2)}) و پیش‌فرض "
                f"({fa_digits(prior, 2)}) بیش از {fa_digits(THRESHOLDS.difficulty_gap, 2)} است"
            )
        z = time_z.get(ei.id)
        if z is not None and z > THRESHOLDS.time_zscore_max:
            reasons.append(
                f"میانگین زمان پاسخ این سؤال غیرعادی بلند است (z={fa_digits(z, 2)} "
                f"بیش از {fa_digits(THRESHOLDS.time_zscore_max, 1)})"
            )

        needs_review = 1 if reasons else 0
        flagged_count += needs_review
        comment = _build_comment(
            correct_pct=correct_pct,
            discrimination=discrimination,
            avg_time_ms=avg_time_ms,
            top_wrong=top_wrong,
            top_wrong_pct=top_wrong_pct,
            misconception=misconception,
            reasons=reasons,
        )

        row = existing.get(ei.id)
        if row is None:
            row = ItemAnalysis(exam_id=exam.id, exam_item_id=ei.id, item_id=q.id)
            db.add(row)
        row.responses_count = len(rows_for_item)
        row.correct_pct = correct_pct
        row.empirical_difficulty = empirical
        row.prior_difficulty = prior
        row.discrimination = discrimination
        row.avg_time_ms = avg_time_ms
        row.top_wrong_option = top_wrong
        row.top_wrong_pct = top_wrong_pct
        row.misconception = misconception
        row.comment_fa = comment
        row.needs_review = needs_review
        row.review_reasons = reasons
        row.computed_at = datetime.utcnow()

        out_rows.append(
            {
                "exam_item_id": ei.id,
                "item_id": q.id,
                "order": ei.order,
                "body": q.body,
                "topic_id": q.topic_id,
                "topic_title": topic_titles.get(q.topic_id, "—"),
                "difficulty": q.difficulty,
                "responses_count": len(rows_for_item),
                "correct_pct": correct_pct,
                "empirical_difficulty": empirical,
                "prior_difficulty": prior,
                "discrimination": discrimination,
                "avg_time_ms": avg_time_ms,
                "top_wrong_option": top_wrong,
                "top_wrong_pct": top_wrong_pct,
                "misconception": misconception,
                "comment_fa": comment,
                "needs_review": bool(needs_review),
                "review_reasons": reasons,
            }
        )

    await db.flush()
    note = None
    if n_attempts == 0:
        note = "هنوز پاسخی برای این آزمون ثبت نشده است؛ محاسبات پس از اولین تلاش فعال می‌شود."
    elif not upper_ids:
        note = (
            f"برای قدرت تفکیک به دست‌کم {fa_digits(THRESHOLDS.min_attempts_discrimination)} "
            "تلاش تصحیح‌شده نیاز است."
        )
    return {
        "ok": True,
        "exam_id": exam.id,
        "attempts": n_attempts,
        "items": out_rows,
        "flagged_count": flagged_count,
        "thresholds": thresholds_out,
        "note_fa": note,
    }
