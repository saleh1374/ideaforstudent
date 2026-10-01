"""آزمون‌های تحلیل نقاط ضعف استان/وزارت (تحلیل قاعده‌محور): شکل پاسخ،
پیشنهادهای غیرخالی، رعایت قاعده حریم خصوصی (بدون عدد سرکوب‌شده)، رتب‌بندی
استان‌ها و گاردهای مجوز (وزارت/استان ↔ مدیر مدرسه)."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_daneshyar.db")

import re

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import AsyncSessionLocal, Base, engine
from app.main import app
from app.models.org import Province
from app.models.stats import NationalTopicStat
from app.services import insights
from scripts.seed import seed


@pytest.fixture()
async def client():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture()
async def seeded(client):
    async with AsyncSessionLocal() as session:
        await seed(session)
    yield


def auth(token):
    return {"Authorization": f"Bearer {token}"}


async def login(client, username, password="pass123"):
    r = await client.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


EXPECTED_KEYS = {
    "scope",
    "generated_at",
    "headline_fa",
    "weakest_subjects",
    "weakest_topics",
    "province_ranking",
    "strengths_fa",
    "recommendations",
}


def assert_shape(body: dict, scope: str) -> None:
    assert EXPECTED_KEYS <= set(body)
    assert body["scope"] == scope
    assert body["headline_fa"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T", body["generated_at"][:11])
    assert body["strengths_fa"] and all(body["strengths_fa"])
    # پیشنهادها هرگز خالی نیستند و قاعده‌محورند
    assert body["recommendations"]
    for rec in body["recommendations"]:
        assert rec["priority"] in (1, 2, 3)
        assert rec["title_fa"] and rec["detail_fa"]
    priorities = [rec["priority"] for rec in body["recommendations"]]
    assert priorities == sorted(priorities)


async def suppressed_topic_ids() -> set[int]:
    async with AsyncSessionLocal() as s:
        rows = (
            await s.execute(
                select(NationalTopicStat).where(NationalTopicStat.is_suppressed == 1)
            )
        ).scalars().all()
        return {r.topic_id for r in rows}


# ------------------------- کمک‌کننده‌های خالص -------------------------


def test_aggregate_subjects_ignores_suppressed_rows():
    """عددِ سرکوب‌شده (زیر حداقل جمعیت) نباید وارد تجمیع درس شود."""
    rows = [
        {"subject": "math", "avg_mastery": 50.0, "weak_ratio": 0.6, "students_count": 20, "suppressed": False},
        {"subject": "math", "avg_mastery": 30.0, "weak_ratio": 0.9, "students_count": 3, "suppressed": True},
        {"subject": "physics", "avg_mastery": 80.0, "weak_ratio": 0.1, "students_count": 10, "suppressed": False},
    ]
    out = insights.aggregate_subjects(rows)
    assert [row["subject"] for row in out] == ["math", "physics"]  # ضعیف‌ترین اول
    assert out[0]["avg_mastery"] == 50.0
    assert out[0]["weak_ratio"] == 0.6
    assert out[0]["students_count"] == 20


def test_build_recommendations_rules_and_fallback():
    s = get_settings()
    # هیچ شرطی برقرار نیست → همیشه حداقل یک پیشنهاد (صفحه خالی نماند)
    fallback = insights.build_recommendations([], 0.0, [], s)
    assert len(fallback) == 1 and fallback[0]["priority"] == 3

    weak = [{"subject": "math", "avg_mastery": 45.0, "weak_ratio": 0.55, "students_count": 30}]
    recs = insights.build_recommendations(
        weak, 0.7, [{"province_id": 2, "name": "استان یزد", "avg_mastery": 40.0}], s
    )
    titles = [rec["title_fa"] for rec in recs]
    assert "بازآموزی پیش‌نیازها" in titles
    assert "تمرین هدفمند" in titles
    assert "بازدید و حمایت ویژه" in titles
    assert "کمبود داده" in titles
    priorities = [rec["priority"] for rec in recs]
    assert priorities == sorted(priorities)


def test_build_strengths_and_headline_are_privacy_safe():
    s = get_settings()
    assert insights.build_strengths(
        [{"topic_id": 1, "title": "مبحث ضعیف", "avg_mastery": 40.0, "suppressed": False}], s
    )
    strong = insights.build_strengths(
        [{"topic_id": 2, "title": "مبحث قوی", "avg_mastery": 90.0, "suppressed": False}], s
    )
    assert "مبحث قوی" in strong[0]

    # وقتی میانگین سرکوب شده، تیتر هیچ عددی نمی‌سازد
    headline = insights.build_headline("national", None, [], 5, 5, s)
    assert "حداقل جمعیت" in headline
    assert "None" not in headline


# ------------------------- سرویس‌های داده‌ای -------------------------


@pytest.mark.anyio
async def test_national_insights_shape_privacy_and_ranking(client, seeded):
    # استان بدون مدرسه/دانش‌آموز → باید سرکوب و بدون عدد گزارش شود
    async with AsyncSessionLocal() as s:
        s.add(Province(name="استان بدون داده", code="EMPTY"))
        await s.commit()

    mtok = await login(client, "ministry")
    r = await client.get("/geo/national/insights", headers=auth(mtok))
    assert r.status_code == 200, r.text
    body = r.json()
    assert_shape(body, "national")

    # ضعیف‌ترین مباحث/درس‌ها فقط از داده‌های قابل نمایش
    assert all(row["avg_mastery"] is not None for row in body["weakest_topics"])
    assert all(row["avg_mastery"] is not None for row in body["weakest_subjects"])
    assert all(row["title"] for row in body["weakest_topics"])
    hidden = await suppressed_topic_ids()
    shown_ids = {row["topic_id"] for row in body["weakest_topics"]}
    assert not (hidden & shown_ids)

    # رتب‌بندی استان‌ها: استان دارای داده + استان بدون داده (بدون عدد)
    ranking = {row["province_id"]: row for row in body["province_ranking"]}
    assert 1 in ranking
    assert ranking[1]["suppressed"] is False
    assert ranking[1]["name"] == "استان تهران"
    assert ranking[1]["avg_mastery"] is not None
    assert ranking[1]["students_count"] >= 10
    empty = next(row for row in body["province_ranking"] if row["suppressed"] is True)
    assert empty["avg_mastery"] is None  # هیچ عدد سرکوب‌شده‌ای عرضه نمی‌شود
    notes = {row["province_id"]: row["note_fa"] for row in body["suppressed_provinces"]}
    assert empty["province_id"] in notes
    assert "داده" in notes[empty["province_id"]]

    # وزارت به استان هم دسترسی دارد (حوزه national زنجیره را می‌پوشاند)
    r = await client.get("/geo/province/1/insights", headers=auth(mtok))
    assert r.status_code == 200 and r.json()["scope"] == "province"


@pytest.mark.anyio
async def test_province_insights_scope_and_permissions(client, seeded):
    ptok = await login(client, "provinceadmin")
    stok = await login(client, "schooladmin")

    # مدیر کل استان: استان خودش → 200
    r = await client.get("/geo/province/1/insights", headers=auth(ptok))
    assert r.status_code == 200, r.text
    body = r.json()
    assert_shape(body, "province")
    assert body["province_id"] == 1
    assert body["province_ranking"] == []  # رتب‌بندی فقط در سطح کشور
    assert all(row["avg_mastery"] is not None for row in body["weakest_topics"])
    hidden = await suppressed_topic_ids()
    assert not (hidden & {row["topic_id"] for row in body["weakest_topics"]})

    # استان دیگر (خارج از حوزه مجوز) → 403
    r = await client.get("/geo/province/999/insights", headers=auth(ptok))
    assert r.status_code == 403

    # مدیر مدرسه نه استان، نه کشور → 403
    r = await client.get("/geo/province/1/insights", headers=auth(stok))
    assert r.status_code == 403
    r = await client.get("/geo/national/insights", headers=auth(stok))
    assert r.status_code == 403

    # بدون توکن → 401
    r = await client.get("/geo/national/insights")
    assert r.status_code == 401
