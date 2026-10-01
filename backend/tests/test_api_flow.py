"""End-to-end API test: seed → login → school overview → exam flow →
SLM updated → RBAC golden rule."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_daneshyar.db")

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.core.db import AsyncSessionLocal, Base, engine, init_models
from app.core.passwords import hash_password
from scripts.seed import seed


@pytest.fixture()
async def client():
    async with engine.begin() as conn:
        from app.core.db import Base
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
async def test_full_flow(client, seeded):
    # ---- student login ----
    r = await client.post("/auth/login", json={"username": "student1", "password": "pass123"})
    assert r.status_code == 200, r.text
    stok = r.json()["token"]

    # ---- student home before any evidence ----
    r = await client.get("/student/home", headers=auth(stok))
    assert r.status_code == 200
    body = r.json()
    assert body["mastery_pct"] == 0.0

    # ---- start and submit exam 1 (official period exam) ----
    r = await client.post("/student/exams/1/start", headers=auth(stok))
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 4

    answers = []
    for it in items:
        # سؤال سوم (|A|=4) جوابش B است؛ بقیه A درست نیستند ولی C برای آیتم دوم درست است
        answers.append({"exam_item_id": it["exam_item_id"], "selected": "C", "confidence": 3, "time_spent_ms": 30000})
    r = await client.post("/student/exams/1/submit", headers=auth(stok), json={"answers": answers})
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["percent"] > 0

    # ---- home reflects mastery now ----
    r = await client.get("/student/home", headers=auth(stok))
    body = r.json()
    assert body["mastery_pct"] > 0
    assert body["errors_total"] > 0

    # ---- error notebook has causes ----
    r = await client.get("/student/errors", headers=auth(stok))
    assert r.status_code == 200
    nb = r.json()
    assert nb["errors_total" if False else "errors"]  # non-empty
    assert len(nb["by_cause"]) >= 1

    # ---- school admin overview aggregates ----
    r = await client.post("/auth/login", json={"username": "schooladmin", "password": "pass123"})
    atok = r.json()["token"]
    r = await client.get("/admin/school/1/overview", headers=auth(atok))
    assert r.status_code == 200, r.text
    ov = r.json()
    assert ov["students_count"] == 5  # 3 در کلاس ۱۰۱ + 2 در کلاس ۱۰۲
    # avg may be None if fewer than min-evidence (3) topics have data — only
    # student1 answered; mastery counts only states with >=3 evidences
    assert ov["status_counts"] is not None

    # ---- RBAC golden rule: teacher without permission cannot grant ----
    r = await client.post("/auth/login", json={"username": "teacher1", "password": "pass123"})
    ttok = r.json()["token"]
    r = await client.post(
        "/admin/permissions/grant",
        headers=auth(ttok),
        json={"grantee_user_id": 5, "role_id": 1, "permission_id": 1, "scope_type": "school", "scope_id": 1},
    )
    assert r.status_code == 403  # lacks manage_permissions

    # ---- employment request flow: school admin submits, district approves ----
    r = await client.post("/auth/login", json={"username": "districtadmin", "password": "pass123"})
    dtok = r.json()["token"]
    r = await client.get("/admin/employment-requests", headers=auth(dtok))
    assert r.status_code == 200

    r = await client.post(
        "/admin/employment-requests",
        headers=auth(atok),  # school admin has manage_employment
        json={
            "school_id": 1,
            "employee_user_id": 6,
            "full_name": "معلم جدید",
            "employment_type": "contractual",
            "organization": "government",
            "subject": "math",
        },
    )
    assert r.status_code == 200, r.text
    req = r.json()
    assert req["status"] in ("pending", "auto_approved")

    if req["status"] == "pending":
        r = await client.post(
            f"/admin/employment-requests/{req['request_id']}/decide",
            headers=auth(dtok),
            json={"approve": True},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "approved"
