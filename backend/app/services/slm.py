"""Pure SLM formulas (student spec §2.3, §7, §2.4, §4.3) — no DB access, so
they are trivially testable. All thresholds come from Settings."""
from __future__ import annotations

import math
from dataclasses import dataclass

from app.core.config import get_settings


@dataclass
class EvidenceRecord:
    weight: float          # e_i
    difficulty: float      # d_i
    partial_credit: float  # c_i in 0..1
    days_ago: float


def mastery(evidences: list[EvidenceRecord]) -> float:
    """M = 100 × Σ(w·d·c·decay) / Σ(w·d·decay), decay = λ^(Δdays/30)."""
    s = get_settings()
    num = 0.0
    den = 0.0
    for ev in evidences:
        decay = s.lambda_decay ** (ev.days_ago / 30.0)
        num += ev.weight * ev.difficulty * ev.partial_credit * decay
        den += ev.weight * ev.difficulty * decay
    if den == 0:
        return 0.0
    return round(100.0 * num / den, 2)


def retention(days_since_last_evidence: float, stability: float) -> float:
    """R = exp(−Δdays / S) — forgetting curve estimate."""
    if days_since_last_evidence <= 0:
        return 1.0
    return math.exp(-days_since_last_evidence / stability)


def next_stability(stability: float, successful: bool) -> float:
    """S ← S×1.8 on success, S ← max(2, S×0.5) on failure."""
    s = get_settings()
    if successful:
        return round(stability * s.stability_success_factor, 3)
    return round(max(s.stability_fail_floor, stability * s.stability_fail_factor), 3)


def effective_mastery(m: float, r: float) -> float:
    """E = M × (0.6 + 0.4×R); forgetting lowers M by at most 40%."""
    s = get_settings()
    floor = s.retention_floor_factor
    return round(m * (floor + (1 - floor) * r), 2)


def status_of(e: float, evidence_count: int) -> str:
    """Display status from effective mastery + minimum-evidence rule."""
    s = get_settings()
    if evidence_count < s.evidence_min_for_status:
        return "unknown"
    if e >= s.threshold_mastered:
        return "mastered"
    if e >= s.threshold_consolidating:
        return "consolidating"
    if e >= s.threshold_weak:
        return "weak"
    return "critical"


def normalized_gain(now_pct: float, prev_pct: float) -> float:
    """g = (now − prev) / (100 − prev); hidden when prev ≥ 95."""
    if prev_pct >= 95:
        return 0.0
    return round((now_pct - prev_pct) / (100.0 - prev_pct), 4)


def percentile_of(x: float, scores: list[float]) -> int:
    """percentile(x) = 100 × (count(<x) + 0.5·count(==x)) / N."""
    if not scores:
        return 0
    n = len(scores)
    below = sum(1 for v in scores if v < x)
    equal = sum(1 for v in scores if v == x)
    return round(100.0 * (below + 0.5 * equal) / n)


def review_ladder() -> list[int]:
    """Spaced review ladder in days: 1,3,7,14,30,60,120."""
    return [int(x) for x in get_settings().review_ladder_days.split(",")]


def next_review_gap(current_index: int, successful: bool) -> tuple[int, int]:
    """Returns (new_index, gap_days); failure drops two rungs."""
    ladder = review_ladder()
    idx = current_index + 1 if successful else max(0, current_index - 2)
    idx = min(idx, len(ladder) - 1)
    return idx, ladder[idx]


def task_priority(severity: float, repeat_count: int, exam_proximity: float, topic_weight: float) -> float:
    """priority = severity × (1+0.25·repeats, capped 2.0) × exam_proximity × topic_weight."""
    repeat_weight = min(1.0 + 0.25 * repeat_count, 2.0)
    return round(severity * repeat_weight * exam_proximity * topic_weight, 4)


def status_rank(status: str) -> int:
    return {"critical": 0, "weak": 1, "consolidating": 2, "mastered": 3, "unknown": 4}.get(status, 4)


# ---------------------------------------------- پیشرفت در برنامه (§4.4)
# P = 100 × Σ( u_k × completed_k ) / Σ( u_k × due_k )   # فقط کارهای سررسیدشده
PLAN_UNIT_WEIGHTS: dict[str, float] = {
    "lesson": 0.25,        # درس
    "practice": 0.30,      # تمرین
    "quiz": 0.10,          # کوییز هفتگی
    "period_exam": 0.25,   # آزمون دوره‌ای / تجمعی
    "remedial": 0.10,      # بستهٔ ترمیمی و بازآزمون
}

# نگاشت task_type برنامه ← واحد فرمول (بخش‌های بدون وزنِ سند، مانند مرور
# فاصله‌دار و آمادگی آزمون تجمعی، در مخرج/صورت وارد نمی‌شوند)
PLAN_TASK_UNIT: dict[str, str] = {
    "lesson": "lesson",
    "practice": "practice",
    "quiz": "quiz",
    "remedial_pack": "remedial",
    "retest": "remedial",
}


def progress_in_plan(entries: list[tuple[str, bool, bool]]) -> float:
    """فرمول «پیشرفت در برنامه» P (§4.4) — محض و بدون دسترسی به دیتابیس.

    entries: [(واحد یا نوع کار، انجام‌شده؟، سررسیدشده تا امروز؟), ...]
    completed_k فقط وقتی ۱ است که شرط انجام برقرار باشد (مثلاً گذراندن
    آزمونک برای درس). اگر هیچ کاری سررسید نشده باشد صفر برمی‌گردد.
    """
    num = 0.0
    den = 0.0
    for unit, completed, due in entries:
        u = PLAN_UNIT_WEIGHTS.get(unit)
        if u is None or not due:
            continue
        den += u
        if completed:
            num += u
    if den == 0:
        return 0.0
    return round(100.0 * num / den, 1)


# ---------------------------------------------------------------- teacher
# دسته‌بندی پنج‌گانه نیاز (سند پنل معلم §6) — first-match wins، به ترتیب جدول سند

def classify_need(
    e: float,
    r: float,
    progress_pct: float | None,
    repeat_count: int,
    prereq_weak: bool = False,
) -> str:
    """Returns one of: intervention | retention_drop | behind | future_risk | ready

    intervention   🔴 تسلط پایین (E < 65) — خطای تکراری اولویت را بیشتر می‌کند
    retention_drop 🟠 قبلاً خوب بوده (E ≥ 65) ولی ماندگاری افت کرده (R < 0.5)
    behind         🟡 تسلط مناسب ولی پیشرفت برنامه کم (< 50٪)
    future_risk    🔵 تسلط فعلی خوب، ولی ماندگاری رو به افت یا پیش‌نیاز ضعیف
    ready          🟢 تسلط بالا + ماندگاری بالا
    """
    s = get_settings()
    if e < s.threshold_consolidating:
        return "intervention"
    if r < 0.5:
        return "retention_drop"
    if progress_pct is not None and progress_pct < 50:
        return "behind"
    if r < 0.75 or prereq_weak:
        return "future_risk"
    return "ready"


def root_cause_decision(prereq_masteries: list[float], threshold: float | None = None) -> str:
    """سند پنل معلم §4: اگر همه پیش‌نیازها بالای آستانه بودند، ریشه خودِ مبحث است؛
    وگرنه ریشه، ضعیف‌ترین پیش‌نیاز در زنجیره است (بازگشتی تا بالای زنجیره)."""
    s = get_settings()
    t = threshold if threshold is not None else s.prerequisite_mastery_threshold
    if not prereq_masteries:
        return "topic"
    return "topic" if all(m >= t for m in prereq_masteries) else "prerequisite"


def weakest_prereq_index(prereq_masteries: list[float]) -> int:
    return min(range(len(prereq_masteries)), key=lambda i: prereq_masteries[i])
