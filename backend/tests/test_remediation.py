"""Phase 4 tests: آزمون هدف‌محور + گردش کار ترمیم/بازآزمون."""
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


async def login(client, username):
    r = await client.post("/auth/login", json={"username": username, "password": "pass123"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


async def take_exam_wrong(client, stok):
    """آزمون دوره ۱ را عمداً خراب می‌دهد → خطای باز تولید می‌شود."""
    r = await client.post("/student/exams/1/start", headers=auth(stok))
    items = r.json()["items"]
    answers = [
        {"exam_item_id": it["exam_item_id"], "selected": "A", "confidence": 3, "time_spent_ms": 5000}
        for it in items
    ]
    r = await client.post("/student/exams/1/submit", headers=auth(stok), json={"answers": answers})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.anyio
async def test_retest_cycle_resolve_and_relapse(client, seeded):
    stok = await login(client, "student1")

    # ۱) قبل از آزمون: خطایی نیست → ساخت بازآزمون رد می‌شود
    r = await client.get("/student/retest/plan", headers=auth(stok))
    assert r.status_code == 200
    assert r.json()["can_build"] is False

    result = await take_exam_wrong(client, stok)
    assert result["percent"] < 100

    # ۲) بعد از آزمون: مباحث دارای خطای باز دیده می‌شوند
    r = await client.get("/student/retest/plan", headers=auth(stok))
    plan = r.json()
    assert plan["can_build"] is True
    assert len(plan["targets"]) >= 1
    assert all(t["causes"] for t in plan["targets"])

    # ۳) ساخت بازآزمون ترمیمی
    r = await client.post("/student/retest/build", headers=auth(stok))
    assert r.status_code == 200, r.text
    built = r.json()
    assert built["ok"] is True
    exam_id = built["exam_id"]
    assert built["item_count"] >= 2

    # خطاها وارد چرخه ترمیم شدند
    r = await client.get("/student/errors", headers=auth(stok))
    statuses = {e["status"] for e in r.json()["errors"]}
    assert "in_remediation" in statuses

    # کار برنامه «بازآزمون» ساخته شد
    r = await client.get("/student/tasks", headers=auth(stok))
    task_types = [t["type"] for t in r.json()["tasks"]]
    assert "retest" in task_types

    # ۴) بازآزمون را نادرست می‌دهم → خطاها باید relapse شوند
    r = await client.post(f"/student/exams/{exam_id}/start", headers=auth(stok))
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    answers = [
        {"exam_item_id": it["exam_item_id"], "selected": "D", "confidence": 3, "time_spent_ms": 3000}
        for it in items
    ]
    r = await client.post(f"/student/exams/{exam_id}/submit", headers=auth(stok), json={"answers": answers})
    assert r.status_code == 200, r.text
    sub = r.json()
    assert "remediation" in sub
    if sub["percent"] < 75:
        assert sub["remediation"]["relapsed"] >= 1
        r = await client.get("/student/errors", headers=auth(stok))
        statuses = {e["status"] for e in r.json()["errors"]}
        assert "relapsed" in statuses


@pytest.mark.anyio
async def test_retest_resolve_when_passing(client, seeded):
    """پاسخ درست در بازآزمون → رفع خطا (resolve)."""
    stok = await login(client, "student1")
    await take_exam_wrong(client, stok)

    r = await client.post("/student/retest/build", headers=auth(stok))
    exam_id = r.json()["exam_id"]

    # برای دانستن پاسخ‌های درست، سؤالات آزمون را مستقیم از دیتابیس می‌خوانیم
    from app.models.assessment import ExamItem, QuestionItem
    from sqlalchemy import select

    async with AsyncSessionLocal() as session:
        eis = (
            await session.execute(select(ExamItem).where(ExamItem.exam_id == exam_id))
        ).scalars().all()
        correct = {}
        for ei in eis:
            q = await session.get(QuestionItem, ei.item_id)
            correct[ei.id] = q.correct_option

    r = await client.post(f"/student/exams/{exam_id}/start", headers=auth(stok))
    items = r.json()["items"]
    answers = [
        {"exam_item_id": it["exam_item_id"], "selected": correct[it["exam_item_id"]], "confidence": 4, "time_spent_ms": 4000}
        for it in items
    ]
    r = await client.post(f"/student/exams/{exam_id}/submit", headers=auth(stok), json={"answers": answers})
    assert r.status_code == 200, r.text
    sub = r.json()
    assert sub["percent"] >= 75
    assert sub["remediation"]["resolved"] >= 1
    assert sub["remediation"]["relapsed"] == 0

    r = await client.get("/student/errors", headers=auth(stok))
    statuses = [e["status"] for e in r.json()["errors"]]
    assert "resolved" in statuses
    assert "in_remediation" not in statuses

    # برنامه بازآزمون هم بسته شد
    r = await client.get("/student/tasks", headers=auth(stok))
    retest_tasks = [t for t in r.json()["tasks"] if t["type"] == "retest"]
    assert all(t["status"] == "done" for t in retest_tasks)


@pytest.mark.anyio
async def test_retest_requires_open_errors(client, seeded):
    """بدون خطای باز، ساخت بازآزمون 400 می‌دهد."""
    stok = await login(client, "student3")  # بدون آزمون/خطا
    r = await client.post("/student/retest/build", headers=auth(stok))
    assert r.status_code == 400
