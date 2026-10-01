"""تحلیل نقاط ضعف برای استان/وزارت (تحلیل قاعده‌محور — «AI نقاط ضعف»):
روایت فارسیِ قطعی و بازتولیدپذیر ساخته‌شده روی تجمیع‌های موجود
(stats_service.topic_stats / overview) با رعایت قاعده حریم خصوصی: هرگز
عددِ سرکوب‌شده (زیر حداقل جمعیت) وارد روایت، فهرست یا پیشنهاد نمی‌شود.

کمک‌کننده‌های خالص (aggregate_subjects / build_recommendations /
build_strengths / build_headline) قابل واحد-آزمایی هستند؛ توابع async فقط
داده می‌خوانند و همان کمک‌کننده‌ها را صدا می‌زنند."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.catalog import Topic
from app.models.org import Province
from app.services import stats_service

SUBJECT_FA = {
    "math": "ریاضی",
    "physics": "فیزیک",
    "chemistry": "شیمی",
    "biology": "زیست‌شناسی",
    "literature": "ادبیات فارسی",
    "arabic": "عربی",
    "english": "زبان انگلیسی",
    "history": "تاریخ",
    "geography": "جغرافیا",
    "religion": "قرآن و تربیت",
}

WEAK_RATIO_TARGET = 0.4   # سهم بالای این نسبت → «تمرین هدفمند»
SUPPRESSED_RATIO_LIMIT = 0.5  # بیش از این سهم مبحث سرکوب‌شده → «کمبود داده»


def subject_fa(subject: str | None) -> str:
    """نام فارسی درس برای روایت (کد ناشناخته همان کد)."""
    if not subject:
        return "نامشخص"
    return SUBJECT_FA.get(subject, subject)


# ------------------------- کمک‌کننده‌های خالص -------------------------


def visible_rows(rows: list[dict]) -> list[dict]:
    """سطرهای قابل اتکا: غیرسرکوب‌شده و دارای میانگین — هیچ عدد سرکوب‌شده‌ای
    از این مسیر عبور نمی‌کند."""
    return [
        r
        for r in rows
        if not r.get("suppressed") and r.get("avg_mastery") is not None
    ]


def aggregate_subjects(rows: list[dict]) -> list[dict]:
    """تجمیع سطح مبحث به سطح درس (میانگین وزنی بر اساس جمعیت داده‌دار) —
    فقط از سطرهای غیرسرکوب‌شده؛ سرکوب‌شده‌ها اصلاً وارد محاسبه نمی‌شوند."""
    buckets: dict[str, dict] = {}
    for row in visible_rows(rows):
        subject = row.get("subject") or "نامشخص"
        students = max(int(row.get("students_count") or 0), 1)
        bucket = buckets.setdefault(
            subject, {"weight": 0.0, "mastery": 0.0, "weak": 0.0, "students": 0}
        )
        bucket["weight"] += students
        bucket["mastery"] += row["avg_mastery"] * students
        bucket["weak"] += float(row.get("weak_ratio") or 0.0) * students
        bucket["students"] = max(bucket["students"], int(row.get("students_count") or 0))

    out = [
        {
            "subject": subject,
            "avg_mastery": round(bucket["mastery"] / bucket["weight"], 1),
            "weak_ratio": round(bucket["weak"] / bucket["weight"], 3),
            "students_count": bucket["students"],
        }
        for subject, bucket in buckets.items()
        if bucket["weight"] > 0
    ]
    out.sort(key=lambda row: row["avg_mastery"])  # ضعیف‌ترین اول
    return out


def build_strengths(rows: list[dict], settings: Settings) -> list[str]:
    """نقاط قوت: مباحث بالای آستانه تسلط (فقط داده‌های قابل نمایش)."""
    strong = sorted(
        visible_rows(rows),
        key=lambda row: -row["avg_mastery"],
    )
    out = [
        f"«{row.get('title') or row['topic_id']}» با میانگین {row['avg_mastery']}٪ بالای آستانه تسلط ({settings.threshold_mastered}٪) است"
        for row in strong
        if row["avg_mastery"] >= settings.threshold_mastered
    ][:3]
    if not out:
        out = [
            "هیچ مبحثی هنوز بالای آستانه تسط نرسیده است؛ اولویت با تثبیت مباحث میانی است"
        ]
    return out


def build_recommendations(
    weak_subjects: list[dict],
    suppressed_ratio: float,
    lagging_provinces: list[dict],
    settings: Settings,
) -> list[dict]:
    """پیشنهادهای قاعده‌محور و قطعی (بدون مدل آماری): حداقل همیشه یک
    پیشنهاد تولید می‌شود تا صفحه خالی نماند."""
    recs: list[dict] = []

    for subject in [
        row for row in weak_subjects
        if row["avg_mastery"] < settings.threshold_consolidating
    ][:2]:
        recs.append(
            {
                "priority": 1,
                "title_fa": "بازآموزی پیش‌نیازها",
                "detail_fa": (
                    f"میانگین تسط «{subject_fa(subject['subject'])}» "
                    f"({subject['avg_mastery']}٪) زیر آستانه تثبیت "
                    f"({settings.threshold_consolidating}٪) است؛ دوره بازآموزی "
                    "پیش‌نیازهای این درس در مدرسه‌های دارای داده برنامه‌ریزی شود."
                ),
            }
        )

    for subject in [
        row for row in weak_subjects if row["weak_ratio"] > WEAK_RATIO_TARGET
    ][:2]:
        percent = round(subject["weak_ratio"] * 100)
        recs.append(
            {
                "priority": 2,
                "title_fa": "تمرین هدفمند",
                "detail_fa": (
                    f"در «{subject_fa(subject['subject'])}» حدود {percent}٪ دانش‌آموزان "
                    "دارای داده زیر آستانه تثبیت‌اند؛ بسته تمرین هدفمند و بازآزمون کوتاه "
                    "برای همین گروه تدوین شود."
                ),
            }
        )

    if lagging_provinces:
        names = "، ".join(p["name"] for p in lagging_provinces[:5])
        recs.append(
            {
                "priority": 1,
                "title_fa": "بازدید و حمایت ویژه",
                "detail_fa": (
                    f"{names} زیر میانگین کشوری تسط هستند؛ بازدید میدانی، "
                    "ارسال مربی و حمایت ویژه در دستور کار قرار گیرد."
                ),
            }
        )

    if suppressed_ratio > SUPPRESSED_RATIO_LIMIT:
        percent = round(suppressed_ratio * 100)
        recs.append(
            {
                "priority": 3,
                "title_fa": "کمبود داده",
                "detail_fa": (
                    f"{percent}٪ مباحث زیر حداقل جمعیت سرکوب شده‌اند؛ ثبت شواهد "
                    "یادگیری بیشتر (تمرین و آزمون کوتاه) برای تحلیل قابل اتکا لازم است."
                ),
            }
        )

    if not recs:
        recs.append(
            {
                "priority": 3,
                "title_fa": "پایش مستمر",
                "detail_fa": (
                    "شاخص‌ها بالای آستانه‌های هشدارند؛ پایش مستمر و تثبیت "
                    "دستاوردها ادامه یابد."
                ),
            }
        )

    recs.sort(key=lambda rec: rec["priority"])
    return recs


def build_headline(
    scope: str,
    avg_mastery: float | None,
    weak_subjects: list[dict],
    suppressed_topics: int,
    total_topics: int,
    settings: Settings,
    province_name: str | None = None,
) -> str:
    """تیتر روایت — وقتی میانگین سرکوب شده هیچ عددی ساخته نمی‌شود."""
    if avg_mastery is None:
        return (
            "داده کافی برای تجمیع سطح بالا وجود ندارد "
            f"(زیر حداقل جمعیت {settings.min_group_size} دانش‌آموز دارای داده)"
        )
    where = province_name if scope == "province" and province_name else "کشور"
    weak_count = len(
        [
            row
            for row in weak_subjects
            if row["avg_mastery"] < settings.threshold_consolidating
        ]
    )
    return (
        f"میانگین تسط {where} {avg_mastery}٪؛ {weak_count} درس زیر آستانه تثبیت "
        f"({settings.threshold_consolidating}٪) و {suppressed_topics} از {total_topics} "
        "مبحث زیر حداقل جمعیت گزارش نمی‌شود."
    )


# ------------------------- توابع داده‌ای (async) -------------------------


async def _topic_rows(db: AsyncSession, province_id: int | None) -> list[dict]:
    """سطرهای تجمیع مبحث (همراه عنوان فارسی) — با بازمحاسبه خودکار در صورت خالی‌بودن."""
    stats = await stats_service.topic_stats(db, province_id)
    titles = {
        t.id: t.title_fa for t in (await db.execute(select(Topic))).scalars()
    }
    return [
        {**row, "title": titles.get(row["topic_id"], f"#{row['topic_id']}")}
        for row in stats["rows"]
    ]


async def province_insights(db: AsyncSession, province_id: int) -> dict:
    """روایت نقاط ضعف یک استان (مجوز view_province_analytics با حوزه استان)."""
    s = get_settings()
    province = await db.get(Province, province_id)
    rows = await _topic_rows(db, province_id)
    overview = await stats_service.overview(db, province_id)

    weak_subjects = aggregate_subjects(rows)
    shown = visible_rows(rows)
    suppressed = len(rows) - len(shown)
    suppressed_ratio = suppressed / len(rows) if rows else 0.0

    return {
        "scope": "province",
        "province_id": province_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "headline_fa": build_headline(
            "province",
            overview["avg_mastery"],
            weak_subjects,
            suppressed,
            len(rows),
            s,
            province.name if province else None,
        ),
        "weakest_subjects": weak_subjects[:5],
        "weakest_topics": [
            {
                "topic_id": row["topic_id"],
                "title": row["title"],
                "subject": row["subject"],
                "avg_mastery": row["avg_mastery"],
                "weak_ratio": row["weak_ratio"],
            }
            for row in shown[:5]
        ],
        "province_ranking": [],
        "suppressed_provinces": [],
        "strengths_fa": build_strengths(rows, s),
        "recommendations": build_recommendations(
            weak_subjects, suppressed_ratio, [], s
        ),
    }


async def national_insights(db: AsyncSession) -> dict:
    """روایت نقاط ضعف کشور (مجوز view_national_analytics با حوزه national) +
    رتب‌بندی استان‌ها؛ استان‌های زیر حداقل جمعیت بدون عدد و جداگانه با
    برچسب «داده‌کافی ندارد» نمایش داده می‌شوند."""
    s = get_settings()
    rows = await _topic_rows(db, None)
    overview = await stats_service.overview(db, None)

    weak_subjects = aggregate_subjects(rows)
    shown = visible_rows(rows)
    suppressed = len(rows) - len(shown)
    suppressed_ratio = suppressed / len(rows) if rows else 0.0

    provinces = list(
        (await db.execute(select(Province).order_by(Province.id))).scalars()
    )
    ranking: list[dict] = []
    suppressed_provinces: list[dict] = []
    for province in provinces:
        ov = await stats_service.overview(db, province.id)
        entry = {
            "province_id": province.id,
            "name": province.name,
            "avg_mastery": ov["avg_mastery"],
            "students_count": ov["students_count"],
            "suppressed": ov["suppressed"],
        }
        ranking.append(entry)
        if ov["suppressed"]:
            suppressed_provinces.append(
                {
                    "province_id": province.id,
                    "name": province.name,
                    "note_fa": "داده‌کافی ندارد",
                }
            )
    # بهترین استان اول؛ سرکوب‌شده‌ها (بدون عدد) در انتها
    ranking.sort(
        key=lambda entry: (entry["suppressed"], -(entry["avg_mastery"] or 0.0))
    )

    national_avg = overview["avg_mastery"]
    lagging = [
        entry
        for entry in ranking
        if not entry["suppressed"]
        and entry["avg_mastery"] is not None
        and national_avg is not None
        and entry["avg_mastery"] < national_avg
    ]

    return {
        "scope": "national",
        "province_id": None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "headline_fa": build_headline(
            "national", national_avg, weak_subjects, suppressed, len(rows), s
        ),
        "weakest_subjects": weak_subjects[:5],
        "weakest_topics": [
            {
                "topic_id": row["topic_id"],
                "title": row["title"],
                "subject": row["subject"],
                "avg_mastery": row["avg_mastery"],
                "weak_ratio": row["weak_ratio"],
            }
            for row in shown[:5]
        ],
        "province_ranking": ranking,
        "suppressed_provinces": suppressed_provinces,
        "strengths_fa": build_strengths(rows, s),
        "recommendations": build_recommendations(
            weak_subjects, suppressed_ratio, lagging, s
        ),
    }
