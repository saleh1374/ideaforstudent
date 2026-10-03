"""Unit tests for pure SLM formulas (student spec §2.3)."""
from app.services.slm import (
    EvidenceRecord,
    effective_mastery,
    mastery,
    next_review_gap,
    next_stability,
    normalized_gain,
    percentile_of,
    retention,
    status_of,
    task_priority,
)


def test_mastery_full_credit_recent():
    evs = [EvidenceRecord(weight=1.0, difficulty=1.2, partial_credit=1.0, days_ago=0)]
    assert mastery(evs) == 100.0


def test_mastery_decay_weights_recency_when_mixed():
    """Decay matters when mixing ages: recent success + old failure > old success + recent failure."""
    good_recent = [
        EvidenceRecord(weight=1.0, difficulty=1.0, partial_credit=1.0, days_ago=1),
        EvidenceRecord(weight=1.0, difficulty=1.0, partial_credit=0.0, days_ago=90),
    ]
    bad_recent = [
        EvidenceRecord(weight=1.0, difficulty=1.0, partial_credit=0.0, days_ago=1),
        EvidenceRecord(weight=1.0, difficulty=1.0, partial_credit=1.0, days_ago=90),
    ]
    assert mastery(good_recent) > mastery(bad_recent)


def test_mastery_uniform_age_ignores_decay():
    """Same-age evidences scale equally — decay cancels out."""
    old = [EvidenceRecord(weight=1.0, difficulty=1.0, partial_credit=1.0, days_ago=90)]
    assert mastery(old) == 100.0


def test_mastery_empty_is_zero():
    assert mastery([]) == 0.0


def test_retention_monotonic():
    assert retention(0, 4) == 1.0
    assert retention(1, 4) > retention(10, 4)
    assert retention(10, 40) > retention(10, 4)


def test_stability_growth_and_floor():
    assert next_stability(4, True) == 7.2
    assert next_stability(2, False) == 2.0  # floor
    assert next_stability(10, False) == 5.0


def test_effective_mastery_forgetting_cap():
    # R = 0 → E = 0.6×M (کاهش حداکثر ۴۰٪)
    assert effective_mastery(80, 0.0) == 48.0
    assert effective_mastery(80, 1.0) == 80.0


def test_status_thresholds():
    assert status_of(90, 5) == "mastered"
    assert status_of(70, 5) == "consolidating"
    assert status_of(45, 5) == "weak"
    assert status_of(20, 5) == "critical"
    assert status_of(95, 2) == "unknown"  # کمتر از ۳ شاهد


def test_normalized_gain():
    assert normalized_gain(70, 40) == 0.5
    assert normalized_gain(95, 95) == 0.0  # hidden


def test_percentile():
    assert percentile_of(50, [10, 20, 60, 70]) == 50
    assert percentile_of(70, [10, 20, 60, 70]) == 88  # (3 + 0.5) / 4 = 87.5 → 88


def test_review_ladder_rungs():
    idx, gap = next_review_gap(0, True)
    assert (idx, gap) == (1, 3)
    idx, gap = next_review_gap(3, False)  # 14 → دو پله پایین → 3
    assert (idx, gap) == (1, 3)


def test_priority_caps_repeat_weight():
    p1 = task_priority(1.0, 0, 1.0, 1.0)
    p2 = task_priority(1.0, 10, 1.0, 1.0)  # repeat weight capped at 2.0
    assert p1 == 1.0
    assert p2 == 2.0


# --------------------- پیشرفت در برنامه، فرمول وزن‌دار P (§4.4) ---------------------


def test_plan_unit_weights_cover_spec_units():
    from app.services.slm import PLAN_TASK_UNIT, PLAN_UNIT_WEIGHTS

    # واحدهای سند §4.4: درس، تمرین، کوییز، آزمون دوره‌ای، ترمیمی
    assert set(PLAN_UNIT_WEIGHTS) == {
        "lesson",
        "practice",
        "quiz",
        "period_exam",
        "remedial",
    }
    assert abs(sum(PLAN_UNIT_WEIGHTS.values()) - 1.0) < 1e-9
    # نگاشت نوع کار برنامه ← واحد فرمول
    assert PLAN_TASK_UNIT["lesson"] == "lesson"
    assert PLAN_TASK_UNIT["practice"] == "practice"
    assert PLAN_TASK_UNIT["quiz"] == "quiz"
    assert PLAN_TASK_UNIT["remedial_pack"] == "remedial"
    assert PLAN_TASK_UNIT["retest"] == "remedial"


def test_progress_in_plan_is_weighted_not_a_count_ratio():
    from app.services.slm import progress_in_plan

    # درس(۰٫۲۵) و کوییز(۰٫۱۰) انجام‌شده، تمرین(۰٫۳۰) انجام‌نشده
    entries = [("lesson", True, True), ("quiz", True, True), ("practice", False, True)]
    expected = round(100.0 * (0.25 + 0.10) / (0.25 + 0.10 + 0.30), 1)
    assert progress_in_plan(entries) == expected
    # نسبت سادهٔ تعداد (۲ از ۳ = ۶۶٫۷) فرق دارد ⇒ واقعاً وزن‌دار است
    assert progress_in_plan(entries) != 66.7

    # همه انجام ⇒ ۱۰۰ و هیچ‌کدام ⇒ ۰
    assert progress_in_plan([("lesson", True, True), ("practice", True, True)]) == 100.0
    assert progress_in_plan([("lesson", False, True), ("practice", False, True)]) == 0.0

    # کارهای سررسیدنشده (آینده) در مخرج وارد نمی‌شوند
    assert progress_in_plan([("practice", False, False)]) == 0.0
    assert progress_in_plan([("practice", True, False), ("lesson", True, True)]) == 100.0

    # بدون ورودی یا فقط با کارهای بدون وزن ⇒ صفر (خطا نمی‌دهد)
    assert progress_in_plan([]) == 0.0
    assert progress_in_plan([("spaced_review", False, True)]) == 0.0
