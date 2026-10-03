"""School / province / national boards (roadmap phase 5 «بردها»).

اصل سراسری سند: نمایش تجمیعی با نام مستعار و حداقل جمعیت ۱۰ نفر — زیر
حد نصاب، عدد اصلاً نمایش داده نمی‌شود (suppressed)، نه تخمین و نه رنگ."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.assessment import Exam, ExamAttempt
from app.models.catalog import Topic
from app.models.org import ClassRoom, Province, School, StudentProfile
from app.models.slm import ErrorRecord, PlanTask, StudentTopicState
from app.services.slm import status_of

# فقط آزمون‌های رسمی و نظارت‌شده وارد بردها می‌شوند (سند دانش‌آموز §8.2)
OFFICIAL_EXAM_TYPES = ("period_exam", "district_exam", "midterm_exam", "final_exam")


def pseudonym(prefix: str, entity_id: int) -> str:
    """نام مستعار پایدار: کلاس «ک-۳»، مدرسه «م-۷» — بدون افشای نام واقعی."""
    # ارقام فارسی برای خوانایی رابط
    digits = str(entity_id).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
    return f"{prefix}-{digits}"


async def _states_of(db: AsyncSession, student_ids: list[int]) -> list[StudentTopicState]:
    if not student_ids:
        return []
    return list(
        (
            await db.execute(
                select(StudentTopicState).where(StudentTopicState.student_user_id.in_(student_ids))
            )
        ).scalars()
    )


def _aggregate(states: list[StudentTopicState], min_group: int) -> dict:
    """تجمیع با قاعده حداقل جمعیت: زیر min_group → همه عددها None + suppressed."""
    students = {s.student_user_id for s in states if s.evidence_count >= 3}
    if len(students) < min_group:
        return {
            "students_with_data": len(students),
            "avg_mastery": None,
            "avg_retention": None,
            "weak_count": None,
            "status_counts": None,
            "suppressed": True,
        }
    with_data = [s for s in states if s.evidence_count >= 3]
    counts: dict[str, int] = {}
    for s in with_data:
        k = status_of(s.effective_mastery, s.evidence_count)
        counts[k] = counts.get(k, 0) + 1
    return {
        "students_with_data": len(students),
        "avg_mastery": round(sum(s.effective_mastery for s in with_data) / len(with_data), 1) if with_data else None,
        "avg_retention": round(sum(s.retention for s in with_data) / len(with_data), 3) if with_data else None,
        "weak_count": sum(1 for s in with_data if s.effective_mastery < get_settings().threshold_consolidating),
        "status_counts": counts,
        "suppressed": False,
    }


async def school_board(db: AsyncSession, school_id: int) -> dict:
    """برد مدرسه: کلاس‌ها با نام مستعار + تجمیع تسلط."""
    s = get_settings()
    classes = (await db.execute(select(ClassRoom).where(ClassRoom.school_id == school_id))).scalars().all()
    rows = []
    for c in classes:
        ids = [
            p.user_id
            for p in (await db.execute(select(StudentProfile).where(StudentProfile.class_id == c.id))).scalars()
        ]
        agg = _aggregate(await _states_of(db, ids), s.min_group_size)
        rows.append({"key": pseudonym("ک", c.id), "kind": "class", **agg})
    # تجمیع کل مدرسه
    all_ids = [
        p.user_id
        for p in (await db.execute(select(StudentProfile).where(StudentProfile.school_id == school_id))).scalars()
    ]
    school_agg = _aggregate(await _states_of(db, all_ids), s.min_group_size)
    rows.sort(key=lambda r: (r["suppressed"], r["avg_mastery"] if r["avg_mastery"] is not None else 999))
    return {
        "scope": "school",
        "school_id": school_id,
        "min_group": s.min_group_size,
        "note_fa": f"اعداد فقط با حداقل {_fa(s.min_group_size)} دانش‌آموز دارای داده نمایش داده می‌شوند؛ نام‌ها مستعار‌اند.",
        "total": school_agg,
        "rows": rows,
    }


async def province_board(db: AsyncSession, province_id: int) -> dict:
    """برد استان: مدارس با نام مستعار."""
    s = get_settings()
    schools = (await db.execute(select(School).where(School.province_id == province_id))).scalars().all()
    rows = []
    for sc in schools:
        ids = [
            p.user_id
            for p in (await db.execute(select(StudentProfile).where(StudentProfile.school_id == sc.id))).scalars()
        ]
        agg = _aggregate(await _states_of(db, ids), s.min_group_size)
        rows.append({"key": pseudonym("م", sc.id), "kind": "school", **agg})
    rows.sort(key=lambda r: (r["suppressed"], r["avg_mastery"] if r["avg_mastery"] is not None else 999))
    return {
        "scope": "province",
        "province_id": province_id,
        "min_group": s.min_group_size,
        "note_fa": f"مقایسه مدارس فقط با حداقل {_fa(s.min_group_size)} دانش‌آموز دارای داده؛ نام مدارس مستعار است.",
        "rows": rows,
    }


async def national_board(db: AsyncSession) -> dict:
    """برد کشور: استان‌ها — نام مستعار + حداقل جمعیت."""
    s = get_settings()
    provinces = (await db.execute(select(Province))).scalars().all()
    # دانش‌آموزان هر استان از طریق مدرسه
    schools = (await db.execute(select(School))).scalars().all()
    prov_of_school = {sc.id: sc.province_id for sc in schools}
    school_ids = [sc.id for sc in schools]
    profiles = (
        await db.execute(select(StudentProfile).where(StudentProfile.school_id.in_(school_ids)))
    ).scalars() if school_ids else []
    by_prov: dict[int, list[int]] = {}
    for p in profiles:
        pid = prov_of_school.get(p.school_id)
        if pid is not None:
            by_prov.setdefault(pid, []).append(p.user_id)
    rows = []
    for prov in provinces:
        agg = _aggregate(await _states_of(db, by_prov.get(prov.id, [])), s.min_group_size)
        rows.append({"key": pseudonym("استان", prov.id), "kind": "province", **agg})
    rows.sort(key=lambda r: (r["suppressed"], r["avg_mastery"] if r["avg_mastery"] is not None else 999))
    return {
        "scope": "national",
        "min_group": s.min_group_size,
        "note_fa": f"رتبه‌بندی استان‌ها با نام مستعار و حداقل جمعیت {_fa(s.min_group_size)} نفر.",
        "rows": rows,
    }


# ---------------- §8.1–8.4: جایگاه من، صدک، رشد، نشان‌ها ----------------

_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def _fa(value) -> str:
    """ارقام فارسی برای متن‌های رابط."""
    return str(value).translate(_FA_DIGITS)

# نام‌های مستعار به‌جای نام واقعی در برد مدرسه (§8.2) — پایدار برای هر شناسه
_ALIAS_POOL = [
    "ستارهٔ شمالی", "پلنگ سپید", "کوهستانی", "بادبادک", "نخلستان", "مهتاب",
    "کویرنورد", "آبشار", "پرندهٔ آزاد", "خورشید", "دشت", "برفک", "نیلگون",
    "شبنم", "ترنم", "کلهر", "ستارهٔ صبح", "گرگ‌و‌میش", "نیلوفر", "یلدا",
]


def student_alias(user_id: int) -> str:
    """نام مستعار دانش‌آموز در بردها — نام واقعی فقط برای خودش/دبیر/مدیر."""
    name = _ALIAS_POOL[user_id % len(_ALIAS_POOL)]
    return f"{name} {str(user_id).translate(_FA_DIGITS)}"


def percentile(scores: list[float], x: float) -> float | None:
    """صدک (§8.3): درصدِ کسانی که نمره‌شان پایین‌تر از x است."""
    if not scores:
        return None
    below = sum(1 for s in scores if s < x)
    equal = sum(1 for s in scores if s == x)
    return round(100.0 * (below + 0.5 * equal) / len(scores), 1)


def growth_gain(now: float | None, prev: float | None) -> float | None:
    """پیشرفت نرمال‌شده §8.3: g = (now − prev) / (100 − prev) — اگر prev ≥ 95 باشد رشد پنهان می‌شود."""
    if now is None or prev is None or prev >= 95 or (100 - prev) <= 0:
        return None
    return round((now - prev) / (100 - prev), 3)


async def _official_scores(db: AsyncSession, student_ids: list[int]) -> dict[int, list[float]]:
    """نمرهٔ آزمون‌های رسمی/نظارت‌شده به‌ترتیب زمانی برای هر دانش‌آموز."""
    if not student_ids:
        return {}
    rows = (
        await db.execute(
            select(ExamAttempt.student_user_id, ExamAttempt.percent, ExamAttempt.submitted_at, ExamAttempt.id)
            .join(Exam, Exam.id == ExamAttempt.exam_id)
            .where(
                ExamAttempt.student_user_id.in_(student_ids),
                ExamAttempt.status == "graded",
                ExamAttempt.percent.is_not(None),
                Exam.exam_type.in_(OFFICIAL_EXAM_TYPES),
            )
            .order_by(ExamAttempt.student_user_id, ExamAttempt.submitted_at.asc(), ExamAttempt.id.asc())
        )
    ).all()
    out: dict[int, list[float]] = {}
    for uid, pct, _sub, _aid in rows:
        out.setdefault(uid, []).append(float(pct))
    return out


async def _mastery_map(db: AsyncSession, student_ids: list[int]) -> dict[int, float]:
    """میانگین تسلط مؤثر (E) هر دانش‌آموز — لنز «تسلط» §8.1."""
    if not student_ids:
        return {}
    s = get_settings()
    by: dict[int, list[float]] = {}
    for st in await _states_of(db, student_ids):
        if st.evidence_count >= s.evidence_min_for_status:
            by.setdefault(st.student_user_id, []).append(st.effective_mastery)
    return {k: round(sum(v) / len(v), 1) for k, v in by.items()}


def _latest(values: dict[int, list[float]]) -> list[float]:
    return [v[-1] for v in values.values() if v]


def _agg_latest(values: dict[int, list[float]], min_group: int) -> dict:
    latest = _latest(values)
    if len(latest) < min_group:
        return {"value": None, "count": len(latest), "suppressed": True}
    return {"value": round(sum(latest) / len(latest), 1), "count": len(latest), "suppressed": False}


LENS_FA = {
    "performance": "عملکرد",
    "growth": "رشد",
    "mastery": "تسلط",
}


async def student_board(db: AsyncSession, student_user_id: int) -> dict:
    """«جایگاه من» در برد مدرسه/استان/کشور (§8.1 سه نما، §8.2 حریم خصوصی، §8.3 فرمول‌ها).

    - سه نما: عملکرد (آخرین آزمون رسمی)، رشد (g نرمال‌شده)، تسط (E با احتساب ماندگاری)
    - برد مدرسه: ده نفر برتر + جایگاه خودم با یک نفر بالا و پایین، با نام مستعار
    - استان/کشور: فقط میانگین، صدک و توزیع — بدون فهرست اسمی
    - هر آمارهٔ گروهی زیر حداقل جمعیت، حذف (suppressed) می‌شود."""
    s = get_settings()
    profile = (
        (
            await db.execute(
                select(StudentProfile).where(StudentProfile.user_id == student_user_id)
            )
        )
        .scalars()
        .first()
    )
    if profile is None:
        return {
            "available": False,
            "note_fa": "برای این حساب پروندهٔ دانش‌آموز ثبت نشده است؛ برد شخصی نمایش داده نمی‌شود.",
        }

    all_profiles = list((await db.execute(select(StudentProfile))).scalars().all())
    schools = {sc.id: sc for sc in (await db.execute(select(School))).scalars().all()}
    my_school_ids = [p.user_id for p in all_profiles if p.school_id == profile.school_id]
    my_school = schools.get(profile.school_id)
    province_id = my_school.province_id if my_school else None
    province_school_ids = [sc.id for sc in schools.values() if sc.province_id == province_id]
    province_ids = [p.user_id for p in all_profiles if p.school_id in province_school_ids]
    all_ids = [p.user_id for p in all_profiles]

    school_scores = await _official_scores(db, my_school_ids)
    province_scores = await _official_scores(db, province_ids)
    national_scores = await _official_scores(db, all_ids)
    school_mastery = await _mastery_map(db, my_school_ids)

    # ---------- دادهٔ خود دانش‌آموز ----------
    mine = school_scores.get(student_user_id, [])
    my_perf = mine[-1] if mine else None
    my_prev = mine[-2] if len(mine) >= 2 else None
    my_growth = growth_gain(my_perf, my_prev)
    my_mastery = school_mastery.get(student_user_id)
    growth_hidden = my_prev is not None and my_prev >= 95

    # ---------- ردیف‌های برد مدرسه (نام مستعار) ----------
    rows: list[dict] = []
    for p in all_profiles:
        if p.school_id != profile.school_id:
            continue
        sc = school_scores.get(p.user_id, [])
        mas = school_mastery.get(p.user_id)
        if not sc and mas is None:
            continue
        rows.append(
            {
                "user_id": p.user_id,
                "alias": student_alias(p.user_id),
                "performance": sc[-1] if sc else None,
                "growth": growth_gain(sc[-1] if sc else None, sc[-2] if len(sc) >= 2 else None),
                "official_count": len(sc),
                "mastery": mas,
                "is_me": p.user_id == student_user_id,
            }
        )

    def ranked(key: str, min_official: int = 0) -> list[dict]:
        vals = [
            r
            for r in rows
            if r.get(key) is not None and r["official_count"] >= min_official
        ]
        vals.sort(key=lambda r: r[key], reverse=True)
        return vals

    rankings: dict[str, dict] = {}
    for lens_key, key, min_official in (
        ("performance", "performance", 1),
        ("growth", "growth", 3),  # §8.3: حداقل ۳ آزمون رسمی برای پایداری رتبهٔ رشد
        ("mastery", "mastery", 0),
    ):
        order = ranked(key, min_official)
        my_pos = next((i for i, r in enumerate(order) if r["is_me"]), None)
        # §8.2: ده نفر برتر + جایگاه من با یک نفر بالا و پایین
        visible_idx: list[int] = list(range(min(10, len(order))))
        if my_pos is not None:
            for i in (my_pos - 1, my_pos, my_pos + 1):
                if 0 <= i < len(order) and i not in visible_idx:
                    visible_idx.append(i)
        visible_idx.sort()
        scale = 100.0 if lens_key == "growth" else 1.0  # رشد به‌صورت درصد (+٪) نمایش داده می‌شود
        rankings[lens_key] = {
            "label_fa": LENS_FA[lens_key],
            "unit": "%",
            "my_rank": (my_pos + 1) if my_pos is not None else None,
            "count": len(order),
            "eligible": (
                my_mastery is not None
                if lens_key == "mastery"
                else (my_perf is not None if lens_key == "performance" else len(mine) >= min_official)
            ),
            "rows": [
                {
                    "rank": i + 1,
                    "alias": order[i]["alias"],
                    "value": round(order[i][key] * scale, 1) if order[i][key] is not None else None,
                    "is_me": order[i]["is_me"],
                }
                for i in visible_idx
            ],
        }

    national_latest = _latest(national_scores)
    national_pct = percentile(national_latest, my_perf) if my_perf is not None else None

    # ---------- مقایسهٔ مبحثی مدرسه/استان (§8.2) ----------
    province_states = await _states_of(db, province_ids)
    school_states = await _states_of(db, my_school_ids)
    my_states = [st for st in school_states if st.student_user_id == student_user_id and st.evidence_count >= 1]
    by_topic_school: dict[int, list[float]] = {}
    for st in school_states:
        if st.evidence_count >= s.evidence_min_for_status:
            by_topic_school.setdefault(st.topic_id, []).append(st.effective_mastery)
    by_topic_province: dict[int, list[float]] = {}
    for st in province_states:
        if st.evidence_count >= s.evidence_min_for_status:
            by_topic_province.setdefault(st.topic_id, []).append(st.effective_mastery)

    topic_ids = sorted({st.topic_id for st in my_states})
    topics = {
        t.id: t
        for t in (
            (await db.execute(select(Topic).where(Topic.id.in_(topic_ids)))).scalars().all()
            if topic_ids
            else []
        )
    }

    def _mean(vals: list[float]) -> float | None:
        return round(sum(vals) / len(vals), 1) if vals else None

    topic_compare = []
    for tid in topic_ids:
        sc_vals = by_topic_school.get(tid, [])
        pr_vals = by_topic_province.get(tid, [])
        sc_ok = len(sc_vals) >= s.min_group_size
        pr_ok = len(pr_vals) >= s.min_group_size
        topic_compare.append(
            {
                "topic_id": tid,
                "title": topics[tid].title_fa if tid in topics else f"مبحث {tid}",
                "school_mean": _mean(sc_vals) if sc_ok else None,
                "school_count": len(sc_vals),
                "province_mean": _mean(pr_vals) if pr_ok else None,
                "province_count": len(pr_vals),
                "gap": (
                    round(_mean(sc_vals) - _mean(pr_vals), 1)
                    if sc_ok and pr_ok and sc_vals and pr_vals
                    else None
                ),
                "suppressed": not (sc_ok and pr_ok),
            }
        )
    topic_compare.sort(key=lambda r: (r["gap"] is None, -(r["gap"] or 0)))

    return {
        "available": True,
        "min_group": s.min_group_size,
        "me": {
            "alias": student_alias(student_user_id),
            "performance": my_perf,
            "prev_performance": my_prev,
            "growth": my_growth,
            "growth_hidden": growth_hidden,
            "growth_hidden_fa": (
                "با نمرهٔ آزمون قبلی ≥ ۹۵٪، رشد نمایش داده نمی‌شود." if growth_hidden else None
            ),
            "mastery": my_mastery,
            "official_count": len(mine),
            "growth_pct": round(my_growth * 100, 1) if my_growth is not None else None,
            "ranks": {k: v["my_rank"] for k, v in rankings.items()},
            "counts": {k: v["count"] for k, v in rankings.items()},
        },
        "lenses": [
            {
                "key": k,
                "label_fa": v["label_fa"],
                "unit": v["unit"],
                "my_rank": v["my_rank"],
                "count": v["count"],
                "eligible": v["eligible"],
                "rows": v["rows"],
            }
            for k, v in rankings.items()
        ],
        "averages": {
            "school": _agg_latest(school_scores, s.min_group_size),
            "province": _agg_latest(province_scores, s.min_group_size),
            "national_percentile": {
                "value": national_pct if len(national_latest) >= s.min_group_size else None,
                "count": len(national_latest),
                "suppressed": len(national_latest) < s.min_group_size,
            },
        },
        "topic_compare": topic_compare,
        "notes_fa": [
            "در برد مدرسه نام‌ها مستعار‌اند؛ نام واقعی فقط برای خودت، دبیر و مدیر مدرسه دیده می‌شود (§8.2).",
            "استان و کشور بدون فهرست اسمی — فقط میانگین، صدک و توزیع (§8.2).",
            f"فقط آزمون‌های رسمی و نظارت‌شده وارد برد می‌شوند؛ خودسنجی و تمرین خانگی حساب نمی‌شود (§8.2).",
            f"هر آمارهٔ گروهی فقط با حداقل {_fa(s.min_group_size)} نفر جمعیت نمایش داده می‌شود (§8.2).",
        ],
    }


async def student_badges(db: AsyncSession, student_user_id: int) -> dict:
    """نشان‌ها و تقدیر (§8.4) — به رشد و رفتار یادگیری پاداش می‌دهد، نه فقط نمرهٔ مطلق."""
    s = get_settings()
    scores = await _official_scores(db, [student_user_id])
    mine = scores.get(student_user_id, [])
    g = growth_gain(mine[-1], mine[-2]) if len(mine) >= 2 else None

    errors = list(
        (await db.execute(select(ErrorRecord).where(ErrorRecord.student_user_id == student_user_id)))
        .scalars()
        .all()
    )
    resolved = [e for e in errors if e.status == "resolved"]
    relapsed = [e for e in errors if e.relapsed_at is not None or e.status == "relapsed"]
    stability_rate = round(len(resolved) / len(errors), 2) if errors else None

    tasks = list(
        (await db.execute(select(PlanTask).where(PlanTask.student_user_id == student_user_id)))
        .scalars()
        .all()
    )
    plan_rate = (
        round(sum(1 for t in tasks if t.status == "done") / len(tasks), 2) if tasks else None
    )

    items = [
        {
            "key": "special_progress",
            "title_fa": "پیشرفت ویژه",
            "description_fa": "رشد نرمال‌شده g ≥ ۰٫۴ نسبت به آزمون قبل",
            "earned": g is not None and g >= 0.4,
            "progress": g,
            "progress_label_fa": f"g = {_fa(round(g, 3))}" if g is not None else "هنوز دو آزمون رسمی نداری",
        },
        {
            "key": "top_retention",
            "title_fa": "ماندگاری برتر",
            "description_fa": "بیش از ۸۰٪ خطاهای باز در یک دوره بسته شده و برنگشته",
            "earned": bool(errors) and len(errors) >= 5 and (stability_rate or 0) >= 0.8,
            "progress": stability_rate,
            "progress_label_fa": (
                f"{_fa(int((stability_rate or 0) * 100))}٪ از {_fa(len(errors))} خطا بسته شده"
                if errors
                else "هنوز خطایی ثبت نشده"
            ),
        },
        {
            "key": "no_repeat_error",
            "title_fa": "بدون خطای تکراری",
            "description_fa": "یک دورهٔ کامل بدون خطای بازگشته (relapse)",
            "earned": bool(errors) and not relapsed,
            "progress": 1.0 if (errors and not relapsed) else 0.0,
            "progress_label_fa": (
                f"{_fa(len(relapsed))} مورد بازگشت" if relapsed else ("بدون بازگشت" if errors else "هنوز داده‌ای نیست")
            ),
        },
        {
            "key": "plan_commitment",
            "title_fa": "مشارکت در برنامه",
            "description_fa": "پایبندی ≥ ۸۰٪ به کارهای برنامهٔ روزانه",
            "earned": bool(tasks) and len(tasks) >= 3 and (plan_rate or 0) >= 0.8,
            "progress": plan_rate,
            "progress_label_fa": (
                f"{_fa(int((plan_rate or 0) * 100))}٪ از {_fa(len(tasks))} کار انجام شده"
                if tasks
                else "برنامه‌ای ثبت نشده"
            ),
        },
    ]
    return {
        "badges": items,
        "earned_count": sum(1 for b in items if b["earned"]),
        "note_fa": "نشان‌ها به رشد و رفتار یادگیری پاداش می‌دهند، نه فقط نمرهٔ مطلق (§8.4).",
    }
