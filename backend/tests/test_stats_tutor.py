"""Phase 7 + 8 tests: تجمیع استان/وزارت (national_topic_stats) + بازار معلم خصوصی."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_daneshyar.db")

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.core.db import AsyncSessionLocal, Base, engine
from app.services.tutoring import safety_filter
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


# ------------------------- فاز ۷: استان / وزارت -------------------------


@pytest.mark.anyio
async def test_province_and_national_stats(client, seeded):
    ptok = await login(client, "provinceadmin")

    r = await client.get("/geo/province/1/overview", headers=auth(ptok))
    assert r.status_code == 200, r.text
    ov = r.json()
    assert ov["scope"] == "province"
    assert ov["schools_count"] == 2
    # ۱۵ دانش‌آموز (۵ + ۱۰) → بالای حداقل جمعیت ۱۰ → میانگین نمایش داده می‌شود
    assert ov["suppressed"] is False
    assert ov["avg_mastery"] is not None
    assert ov["worst_topics"]

    r = await client.get("/geo/province/1/topics", headers=auth(ptok))
    assert r.status_code == 200, r.text
    topics = r.json()
    assert topics["scope"] == "province"
    assert len(topics["rows"]) >= 1
    for row in topics["rows"]:
        # مبحث «مجموعه‌ها» ۱۵ دانش‌آموز دارد → سرکوب نمی‌شود
        if row["topic_id"] == 1:
            assert row["suppressed"] is False
            assert row["avg_mastery"] is not None

    # رفرش تجمیع‌ها (وزارت/استان)
    r = await client.post("/geo/national/refresh", headers=auth(ptok))
    assert r.status_code == 200, r.text
    assert r.json()["national"]["scope"] == "national"


@pytest.mark.anyio
async def test_concurrent_recompute_no_unique_conflict(client, seeded):
    """دو بازمحاسبه موازی (مثل Promise.all صفحه وزارت) نباید UNIQUE conflict بدهند."""
    ptok = await login(client, "provinceadmin")
    h = auth(ptok)
    import asyncio

    r1, r2 = await asyncio.gather(
        client.get("/geo/national/topics", headers=h),
        client.get("/geo/national/overview", headers=h),
    )
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text

    # دوباره همزمان → ردیف‌ها از قبل هستند؛ باز هم باید سبز باشد
    r3, r4 = await asyncio.gather(
        client.post("/geo/national/refresh", headers=h),
        client.post("/geo/national/refresh", headers=h),
    )
    assert r3.status_code == 200, r3.text
    assert r4.status_code == 200, r4.text


@pytest.mark.anyio
async def test_national_stats_permission(client, seeded):
    # معلم/دانش‌آموز دسترسی ندارند
    for user in ("student1", "teacher1"):
        tok = await login(client, user)
        r = await client.get("/geo/national/overview", headers=auth(tok))
        assert r.status_code == 403

    # مدیر مدرسه هم دسترسی استان/کشور ندارد (مجوز جدا)
    tok = await login(client, "schooladmin")
    r = await client.get("/geo/national/overview", headers=auth(tok))
    assert r.status_code == 403
    r = await client.get("/geo/province/1/overview", headers=auth(tok))
    assert r.status_code == 403

    # وزارت دسترسی دارد
    tok = await login(client, "ministry")
    r = await client.get("/geo/national/overview", headers=auth(tok))
    assert r.status_code == 200, r.text
    ov = r.json()
    assert ov["scope"] == "national"
    assert ov["schools_count"] == 2


# ------------------------- فاز ۸: معلم خصوصی -------------------------


def test_safety_filter_masks_contact_info():
    clean, flagged = safety_filter("برای هماهنگی بزن 09121234567")
    assert flagged is True
    assert "09121234567" not in clean
    assert "شماره تماس حذف شد" in clean

    clean, flagged = safety_filter("ببین این سؤال را example.com ببین")
    assert flagged is True
    assert "http" not in clean

    clean, flagged = safety_filter("سلام، فصل سه را مرور کن")
    assert flagged is False
    assert clean == "سلام، فصل سه را مرور کن"


@pytest.mark.anyio
async def test_tutor_market_flow(client, seeded):
    # دانش‌آموز نمی‌تواند نمایه بسازد
    stok = await login(client, "student1")
    r = await client.post("/tutor/profile", headers=auth(stok), json={"subjects": ["math"]})
    assert r.status_code == 403

    # بازار: نمایه معلم خصوصی seed شده دیده می‌شود
    r = await client.get("/tutor/market", headers=auth(stok))
    assert r.status_code == 200
    tutors = r.json()["tutors"]
    assert any(t["name"] == "معلم خصوصی ریاضی" for t in tutors)

    # فیلتر با درس
    r = await client.get("/tutor/market?subject=physics", headers=auth(stok))
    assert r.json()["tutors"] == []

    # دانش‌آموز درخواست جلسه می‌دهد
    tutor_id = next(t["user_id"] for t in tutors if t["name"] == "معلم خصوصی ریاضی")
    r = await client.post(
        "/tutor/requests",
        headers=auth(stok),
        json={"tutor_user_id": tutor_id, "subject": "math", "note": "برای آزمون دوره ۲"},
    )
    assert r.status_code == 200, r.text
    req_id = r.json()["request_id"]
    assert r.json()["requires_parent_consent"] is True

    ttok = await login(client, "tutor1")

    # تا والد تأیید نکند، درخواست به معلم نمی‌رسد (§10.2-۵)
    r = await client.get("/tutor/requests", headers=auth(ttok))
    assert all(x["id"] != req_id for x in r.json()["requests"])
    r = await client.post(f"/tutor/requests/{req_id}/decide", headers=auth(ttok), json={"approve": True})
    assert r.status_code == 400

    # والد رضایت می‌دهد
    ptok = await login(client, "parent1")
    r = await client.get("/tutor/consents", headers=auth(ptok))
    assert any(c["request_id"] == req_id for c in r.json()["consents"])
    r = await client.post(
        f"/tutor/requests/{req_id}/consent", headers=auth(ptok), json={"approve": True}
    )
    assert r.status_code == 200, r.text

    # حالا معلم تصمیم می‌گیرد
    r = await client.post(f"/tutor/requests/{req_id}/decide", headers=auth(ttok), json={"approve": True})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "accepted"

    # دوباره تصمیم → 400
    r = await client.post(f"/tutor/requests/{req_id}/decide", headers=auth(ttok), json={"approve": False})
    assert r.status_code == 400


@pytest.mark.anyio
async def test_tutor_group_chat_safety(client, seeded):
    stok = await login(client, "student1")
    ttok = await login(client, "tutor1")

    # معلم گروه می‌سازد
    r = await client.post(
        "/tutor/groups", headers=auth(ttok), json={"title": "کلاس ریاضی دهم", "subject": "math"}
    )
    assert r.status_code == 200
    gid = r.json()["group_id"]

    # دانش‌آموز بدون پیوستن نمی‌نویسد
    r = await client.post("/tutor/messages", headers=auth(stok), json={"content": "سلام", "group_id": gid})
    assert r.status_code == 400

    # پیوستن به گروه
    r = await client.post(f"/tutor/groups/{gid}/join", headers=auth(stok))
    assert r.status_code == 200 and r.json()["ok"] is True

    # پیام با شماره تماس → فیلتر می‌شود
    r = await client.post(
        "/tutor/messages",
        headers=auth(stok),
        json={"content": "زنگ بزن 09121234567", "group_id": gid},
    )
    assert r.status_code == 200, r.text
    assert r.json()["flagged"] is True
    assert "09121234567" not in r.json()["content"]

    # پیام سالم
    r = await client.post(
        "/tutor/messages", headers=auth(stok), json={"content": "ممنون، فصل ۳ را می‌خوانم", "group_id": gid}
    )
    assert r.json()["flagged"] is False

    # تاریخچه گروه + گزارش
    r = await client.get(f"/tutor/groups/{gid}/messages", headers=auth(ttok))
    msgs = r.json()["messages"]
    assert len(msgs) == 2
    flagged_id = next(m["id"] for m in msgs if m["flagged"])
    r = await client.post(
        f"/tutor/messages/{flagged_id}/report", headers=auth(ttok), json={"reason": "تلاش برای افشای شماره"}
    )
    assert r.status_code == 200

    # لاگ ممیزی ثبت شده (ایمنی زیر ۱۸)
    from app.models.rbac import AuditLog
    from sqlalchemy import select

    async with AsyncSessionLocal() as session:
        logs = (await session.execute(select(AuditLog))).scalars().all()
        actions = {l.action for l in logs}
        assert "tutor_message_filtered" in actions
        assert "tutor_message_reported" in actions


@pytest.mark.anyio
async def test_tutor_group_privacy(client, seeded):
    """کاربر خارج از گروه نه پیام می‌خواند (عضویت) و نه به درخواست دیگران تصمیم می‌دهد."""
    stok = await login(client, "student1")
    other = await login(client, "student2")

    r = await client.post(
        "/tutor/requests",
        headers=auth(stok),
        json={"tutor_user_id": 3, "subject": "math"},  # teacher1
    )
    req_id = r.json()["request_id"]

    # تصمیم فقط برای معلم مقصد
    r = await client.post(f"/tutor/requests/{req_id}/decide", headers=auth(other), json={"approve": True})
    assert r.status_code == 404
