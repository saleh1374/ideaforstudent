"""School admin analytics tests (سند مدیر مدرسه §3-§8)."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_daneshyar.db")

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.core.db import AsyncSessionLocal, Base, engine
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


@pytest.mark.anyio
async def test_school_analytics_flow(client, seeded):
    r = await client.post("/auth/login", json={"username": "schooladmin", "password": "pass123"})
    h = auth(r.json()["token"])

    # ---------------- مقایسه کلاس‌های ریاضی (§7) ----------------
    r = await client.get("/admin/school/1/classes-compare/math", headers=h)
    assert r.status_code == 200, r.text
    cmp = r.json()
    assert cmp["subject"] == "math"
    assert len(cmp["rows"]) == 2  # کلاس ۱۰۱ و ۱۰۲
    names = {row["class_name"] for row in cmp["rows"]}
    assert names == {"۱۰۱", "۱۰۲"}
    # هر ردیف معلم خودش را دارد
    teachers = {row["teacher"]["full_name"] for row in cmp["rows"]}
    assert teachers == {"آقای احمدی", "خانم کریمی"}
    # هر دو کلاس میانگین دارند؛ مرتب‌شده صعودی بر اساس ضعف
    masteries = [row["avg_mastery"] for row in cmp["rows"]]
    assert masteries == sorted(masteries)
    assert all(row["gap_vs_school_avg"] is not None for row in cmp["rows"])
    # جمعیت هر کلاس ۲-۳ نفر است؛ پرچم افت فقط با جمعیت کافی (MIN_GROUP=3)
    for row in cmp["rows"]:
        assert isinstance(row["drop_flag"], bool)

    # ---------------- سامانه نیازمند بررسی (§5) ----------------
    r = await client.get("/admin/school/1/attention-flags", headers=h)
    assert r.status_code == 200, r.text
    flags = r.json()["flags"]
    # دانش‌آموز ۱۰۱ سوم بعد از آزمون ضعیف می‌شود؛ پرچم‌ها باید ساختار درست داشته باشند
    for f in flags:
        assert f["flag_type"] in {"low_mastery_majority", "high_repeats", "ineffective_intervention", "low_platform_usage"}
        assert f["evidence_fa"] and f["action_fa"]

    # ---------------- نمایه سبک معلمان (§4) ----------------
    r = await client.get("/admin/school/1/teachers", headers=h)
    assert r.status_code == 200, r.text
    profiles = r.json()["profiles"]
    assert len(profiles) == 2
    by_teacher = {p["teacher_name"]: p for p in profiles}
    assert by_teacher["خانم کریمی"]["class_mastery"] > by_teacher["آقای احمدی"]["class_mastery"]
    assert all(p["note_fa"] for p in profiles)
    # بدون امتیاز عددی کلی (اصل «شاخص عینی، نه حکم»)
    assert all("score" not in p for p in profiles)

    # ---------------- تشخیص چندعاملی (§6) ----------------
    r = await client.get("/admin/classes/1/diagnosis", headers=h)
    assert r.status_code == 200, r.text
    diag = r.json()
    assert "error_causes" in diag and "grounded_actions_fa" in diag
    assert diag["note_fa"]

    # ---------------- خلاصه کلاس ----------------
    r = await client.get("/admin/classes/2/summary", headers=h)
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["class_id"] == 2
    assert s["avg_mastery"] is not None and s["avg_mastery"] > 80  # کلاس قوی

    # ---------------- گارد دسترسی: دانش‌آموز → ۴۰۳ ----------------
    r = await client.post("/auth/login", json={"username": "student1", "password": "pass123"})
    r = await client.get("/admin/school/1/attention-flags", headers=auth(r.json()["token"]))
    assert r.status_code == 403


@pytest.mark.anyio
async def test_teacher_view_matches_admin_overview(client, seeded):
    """سازگاری هسته مشترک: تسلط کلاس ۱۰۲ در نمایه معلم == خلاصه مدیر."""
    r = await client.post("/auth/login", json={"username": "schooladmin", "password": "pass123"})
    h = auth(r.json()["token"])
    r = await client.get("/admin/classes/2/summary", headers=h)
    admin_summary = r.json()

    r = await client.post("/auth/login", json={"username": "teacher2", "password": "pass123"})
    th = auth(r.json()["token"])
    r = await client.get("/teacher/classes/2/radar", headers=th)
    assert r.status_code == 200, r.text
    radar = r.json()
    assert radar["total_students"] == 2
    # هر دو شاخص از همان SLM می‌آیند — تسلط کل رادار باید نزدیک میانگین مدیر باشد
    radar_mean = round(sum(row["avg_mastery"] for row in radar["rows"]) / len(radar["rows"]), 1)
    assert abs(radar_mean - admin_summary["avg_mastery"]) <= 0.5
