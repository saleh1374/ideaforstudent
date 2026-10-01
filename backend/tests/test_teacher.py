"""Teacher panel tests: 5-need classification units + API flow (radar,
root-cause, groups, class-ownership guard)."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_daneshyar.db")

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.core.db import AsyncSessionLocal, Base, engine
from app.services.slm import classify_need, root_cause_decision, weakest_prereq_index
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


# ------------------------- pure classification -------------------------

def test_classify_low_mastery_is_intervention():
    assert classify_need(e=40, r=1.0, progress_pct=None, repeat_count=0) == "intervention"


def test_classify_retention_drop():
    # تسلط خوب (E≥65 به‌خاطر M بالا) ولی R پایین
    assert classify_need(e=77, r=0.42, progress_pct=None, repeat_count=0) == "retention_drop"


def test_classify_behind_in_plan():
    assert classify_need(e=80, r=0.9, progress_pct=30, repeat_count=0) == "behind"


def test_classify_future_risk():
    assert classify_need(e=80, r=0.65, progress_pct=80, repeat_count=0) == "future_risk"
    assert classify_need(e=80, r=0.9, progress_pct=80, repeat_count=0, prereq_weak=True) == "future_risk"


def test_classify_ready():
    assert classify_need(e=95, r=0.95, progress_pct=80, repeat_count=0) == "ready"


def test_root_cause_decision_threshold():
    assert root_cause_decision([80, 90]) == "topic"
    assert root_cause_decision([80, 50]) == "prerequisite"
    assert root_cause_decision([]) == "topic"


def test_weakest_prereq_index():
    assert weakest_prereq_index([80, 30, 60]) == 1


# ------------------------------ API flow ------------------------------

@pytest.mark.anyio
async def test_teacher_flow(client, seeded):
    # teacher login
    r = await client.post("/auth/login", json={"username": "teacher1", "password": "pass123"})
    ttok = r.json()["token"]
    h = auth(ttok)

    # classes of this teacher
    r = await client.get("/teacher/me/classes", headers=h)
    assert r.status_code == 200, r.text
    classes = r.json()["classes"]
    assert len(classes) == 1
    cid = classes[0]["class_id"]
    assert classes[0]["students_count"] == 3

    # student1 takes the exam: 1 correct out of 4 → تسلط پایین → مداخله
    r = await client.post("/auth/login", json={"username": "student1", "password": "pass123"})
    stok = r.json()["token"]
    r = await client.post("/student/exams/1/start", headers=auth(stok))
    items = r.json()["items"]
    answers = []
    for it in items:
        sel = "C" if it["order"] == 2 else "A"
        answers.append({"exam_item_id": it["exam_item_id"], "selected": sel, "confidence": 3, "time_spent_ms": 30000})
    r = await client.post("/student/exams/1/submit", headers=auth(stok), json={"answers": answers})
    assert r.status_code == 200

    # ---------------- radar ----------------
    r = await client.get(f"/teacher/classes/{cid}/radar", headers=h)
    assert r.status_code == 200, r.text
    radar = r.json()
    assert radar["total_students"] == 3
    rows = radar["rows"]
    assert len(rows) >= 2  # مباحثی که کلاس رویشان داده دارد
    weakest = rows[0]  # مرتب‌شده بر اساس کمترین تسلط
    assert weakest["avg_mastery"] < 65
    assert weakest["weak_count"] >= 1

    # ---------------- groups (۵ نوع نیاز) ----------------
    r = await client.get(f"/teacher/classes/{cid}/groups", headers=h)
    assert r.status_code == 200, r.text
    groups = {g["need"]: g for g in r.json()["groups"]}
    assert len(groups) == 5

    def need_of(full_name: str) -> str:
        for g in groups.values():
            if any(s["full_name"] == full_name for s in g["students"]):
                return g["need"]
        raise AssertionError(f"student {full_name} not in any group")

    assert need_of("محمد رضایی") == "intervention"    # تسلط پایین بعد از آزمون
    assert need_of("علی کاظمی") == "retention_drop"   # همه درست ولی ۲۰ روز قبل
    assert need_of("سارا موسوی") == "ready"           # قوی و تازه

    # هر گروه یک اقدام پیشنهادی مشخص دارد (از داده به اقدام)
    assert all(g["action"] for g in groups.values())

    # ---------------- root-cause ----------------
    # مبحث «تعداد زیرمجموعه‌ها» (prereq = مجموعه‌ها): میانگین پیش‌نیاز < 65 → ریشه پیش‌نیاز
    topic2 = next(t for t in rows if t["title"].startswith("تعداد"))
    r = await client.get(f"/teacher/classes/{cid}/root-cause/{topic2['topic_id']}", headers=h)
    assert r.status_code == 200, r.text
    rc = r.json()
    assert rc["topic"]["topic_id"] == topic2["topic_id"]
    assert len(rc["chain"]) >= 1
    if rc["root_reason"] == "prerequisite":
        assert "پیش‌نیاز" in rc["diagnosis"]
        assert rc["root"]["mastery"] == min(step["mastery"] for step in rc["chain"])
    else:
        assert "خودِ" in rc["diagnosis"]

    # ---------------- students list ----------------
    r = await client.get(f"/teacher/classes/{cid}/students", headers=h)
    assert r.status_code == 200
    students = r.json()["students"]
    assert len(students) == 3
    assert all("need_label" in s for s in students)


@pytest.mark.anyio
async def test_teacher_cannot_access_other_class(client, seeded):
    # student tries teacher endpoint → 403
    r = await client.post("/auth/login", json={"username": "student1", "password": "pass123"})
    stok = r.json()["token"]
    r = await client.get("/teacher/classes/1/radar", headers=auth(stok))
    assert r.status_code == 403

    # teacher1 owns class 1 only; class 2 does not exist → 403 (not owner)
    r = await client.post("/auth/login", json={"username": "teacher1", "password": "pass123"})
    ttok = r.json()["token"]
    r = await client.get("/teacher/classes/999/radar", headers=auth(ttok))
    assert r.status_code == 403
