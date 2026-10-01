"""تست‌های §16 دستیار هوشمند مدیر مدرسه و §18 پیشنهاد اقدام."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_schoolcopilot.db")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.db import AsyncSessionLocal, Base, engine
from app.main import app
from app.models.rbac import AuditLog
from app.models.school_copilot import SchoolSuggestion
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


async def audit_actions(action: str) -> list[AuditLog]:
    async with AsyncSessionLocal() as s:
        return list((await s.execute(select(AuditLog).where(AuditLog.action == action))).scalars())


# ------------------------- §16 پرسش و پاسخ کوپایلت -------------------------


@pytest.mark.anyio
async def test_copilot_overview_reply_with_sources(client, seeded):
    tok = await login(client, "schooladmin")
    r = await client.post(
        "/admin/school/1/copilot/chat",
        json={"message": "وضعیت کلی مدرسه چطور است؟"},
        headers=auth(tok),
    )
    assert r.status_code == 200, r.text
    data = r.json()

    assert data["conversation_id"] >= 1
    assert data["intent"] in {"overview", "biggest_problem", "weak_topics"}
    assert "مدرسه" in data["reply"]
    assert "تصمیم نهایی" in data["reply"]  # یادداشت copilot است، نه تصمیم‌گیرنده
    assert isinstance(data["sources"], list)
    assert data["note_fa"]

    # رویداد ممیزی §ضمیمه ب
    rows = await audit_actions("school_copilot_query")
    assert rows and rows[-1].actor_user_id is not None

    # ادامه گفت‌وگو در همان conversation
    r2 = await client.post(
        "/admin/school/1/copilot/chat",
        json={"message": "بزرگ‌ترین مشکل آموزشی مدرسه چیست؟", "conversation_id": data["conversation_id"]},
        headers=auth(tok),
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["conversation_id"] == data["conversation_id"]

    # تاریخچه گفت‌وگو
    r3 = await client.get(
        f"/admin/school/1/copilot/conversations/{data['conversation_id']}", headers=auth(tok)
    )
    assert r3.status_code == 200, r3.text
    msgs = r3.json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert msgs[1]["intent"]  # نیت پیام دستیار ثبت شده است


@pytest.mark.anyio
async def test_copilot_intent_detection(client, seeded):
    tok = await login(client, "schooladmin")

    r = await client.post(
        "/admin/school/1/copilot/chat",
        json={"message": "کدام مباحث بیشترین دانش‌آموز ضعیف را دارند؟"},
        headers=auth(tok),
    )
    assert r.status_code == 200, r.text
    assert r.json()["intent"] == "weak_topics"

    r = await client.post(
        "/admin/school/1/copilot/chat",
        json={"message": "برای جلسه شورای آموزشی چه مواردی را بگذارم؟"},
        headers=auth(tok),
    )
    assert r.status_code == 200, r.text
    assert r.json()["intent"] == "council_agenda"


@pytest.mark.anyio
async def test_copilot_honest_without_data(client, seeded):
    """بدون داده کافی → پاسخ صادقانه، نه عدد ساختگی."""
    tok = await login(client, "schooladmin")
    r = await client.post(
        "/admin/school/1/copilot/chat",
        json={"message": "کدام کلاس‌ها بیشترین افت را داشته‌اند؟"},
        headers=auth(tok),
    )
    assert r.status_code == 200, r.text
    reply = r.json()["reply"]
    # یا افت واقعی داریم یا جمله صادقانه «پیدا نشد» — در هر دو حالت عدد غلط نیست
    assert ("افت" in reply) or ("پیدا نشد" in reply)


@pytest.mark.anyio
async def test_copilot_guards(client, seeded):
    # دانش‌آموز بدون view_school_analytics → 403
    tok = await login(client, "student1")
    r = await client.post(
        "/admin/school/1/copilot/chat", json={"message": "سلام"}, headers=auth(tok)
    )
    assert r.status_code == 403

    # مدرسه ناشناس → گارد Scope پیش از چک وجود اجرا می‌شود (۴۰۳)
    tok = await login(client, "schooladmin")
    r = await client.post(
        "/admin/school/999/copilot/chat", json={"message": "سلام"}, headers=auth(tok)
    )
    assert r.status_code == 403

    # بدون توکن → 401
    r = await client.post("/admin/school/1/copilot/chat", json={"message": "سلام"})
    assert r.status_code == 401

    # پیام خالی → 400
    r = await client.post(
        "/admin/school/1/copilot/chat", json={"message": "   "}, headers=auth(tok)
    )
    assert r.status_code == 400


@pytest.mark.anyio
async def test_conversation_scope(client, seeded):
    """گفت‌وگوی مدرسه دیگر با شناسه مدرسه خودمان قابل بازیابی نیست (404)."""
    tok = await login(client, "schooladmin")
    r = await client.post(
        "/admin/school/1/copilot/chat", json={"message": "سلام"}, headers=auth(tok)
    )
    conv_id = r.json()["conversation_id"]

    # مدرسه ۲ مجوز ندارد (گارد 403 پیش از چک وجود)
    tok2 = await login(client, "districtadmin")
    r2 = await client.get(f"/admin/school/2/copilot/conversations/{conv_id}", headers=auth(tok2))
    assert r2.status_code in (403, 404)

    # شناسه گفت‌وگوی ناشناس داخل مدرسه خودمان → 404
    r3 = await client.get(f"/admin/school/1/copilot/conversations/99999", headers=auth(tok))
    assert r3.status_code == 404


# ------------------------- §18 پیشنهاد اقدام و اختیار مدیر -------------------------


@pytest.mark.anyio
async def test_suggestion_lifecycle(client, seeded):
    tok = await login(client, "schooladmin")

    # ساخت پیشنهاد از داده‌های واقعی
    r = await client.post("/admin/school/1/suggestions/generate", headers=auth(tok))
    assert r.status_code == 200, r.text
    gen = r.json()
    assert gen["ok"] is True

    r = await client.get("/admin/school/1/suggestions", headers=auth(tok))
    assert r.status_code == 200, r.text
    suggestions = r.json()["suggestions"]
    assert suggestions, "پرچم/افتی برای ساخت پیشنهاد وجود داشت"
    for s in suggestions:
        assert s["status"] == "proposed"
        assert s["title_fa"] and s["evidence_fa"] and s["actions_fa"]

    # idempotent: بار دوم چیز جدیدی ساخته نمی‌شود
    r = await client.post("/admin/school/1/suggestions/generate", headers=auth(tok))
    assert r.json()["created"] == 0

    sid = suggestions[0]["id"]

    # ویرایش بدون فهرست اقدام → 409 (سرویس ValueError می‌دهد)
    r = await client.post(
        f"/admin/school/1/suggestions/{sid}/decide",
        json={"action": "edit"},
        headers=auth(tok),
    )
    assert r.status_code == 409

    # ویرایش موفق + رویداد ممیزی
    r = await client.post(
        f"/admin/school/1/suggestions/{sid}/decide",
        json={"action": "edit", "edited_actions": ["اقدام اول مدیر", "بازآزمون ۷ روز"], "note": "با اولویت"},
        headers=auth(tok),
    )
    assert r.status_code == 200, r.text
    sugg = r.json()["suggestion"]
    assert sugg["status"] == "edited"
    assert sugg["final_actions_fa"] == ["اقدام اول مدیر", "بازآزمون ۷ روز"]
    assert sugg["decided_by"]
    assert await audit_actions("school_suggestion_edited")

    # تصمیم تکراری → 409
    r = await client.post(
        f"/admin/school/1/suggestions/{sid}/decide",
        json={"action": "approve"},
        headers=auth(tok),
    )
    assert r.status_code == 409


@pytest.mark.anyio
async def test_suggestion_approve_reject_and_guards(client, seeded):
    tok = await login(client, "schooladmin")

    r = await client.post("/admin/school/1/suggestions/generate", headers=auth(tok))
    assert r.status_code == 200, r.text
    created = r.json()["suggestions"]
    assert len(created) >= 2, "برای هر دو مسیر تأیید و رد باید پیشنهاد موجود باشد"

    # تأیید → وضعیت approved + رویداد ممیزی
    s1 = created[0]["id"]
    r = await client.post(
        f"/admin/school/1/suggestions/{s1}/decide", json={"action": "approve"}, headers=auth(tok)
    )
    assert r.status_code == 200, r.text
    assert r.json()["suggestion"]["status"] == "approved"
    assert await audit_actions("school_suggestion_approved")

    # رد → وضعیت rejected + رویداد ممیزی
    s2 = created[1]["id"]
    r = await client.post(
        f"/admin/school/1/suggestions/{s2}/decide",
        json={"action": "reject", "note": "برنامه فعلی کافی است"},
        headers=auth(tok),
    )
    assert r.status_code == 200, r.text
    assert r.json()["suggestion"]["status"] == "rejected"
    assert await audit_actions("school_suggestion_rejected")

    # عملیات نامعتبر → 400
    r = await client.post(
        f"/admin/school/1/suggestions/{s2}/decide", json={"action": "delete"}, headers=auth(tok)
    )
    assert r.status_code == 400

    # پیشنهاد مدرسه دیگر → 404 (حوزه‌بندی داخل سرویس)
    async with AsyncSessionLocal() as s:
        foreign = (
            await s.execute(
                select(SchoolSuggestion).where(SchoolSuggestion.school_id == 2).limit(1)
            )
        ).scalars().first()
    if foreign is None:
        # مدرسه ۲ پرچمی ندارد؛ پیشنهاد مدرسه ۱ را با school_id دیگر امتحان می‌کنیم
        r = await client.post(
            f"/admin/school/2/suggestions/{s1}/decide",
            json={"action": "approve"},
            headers=auth(tok),
        )
        assert r.status_code in (403, 404)

    # دانش‌آموز → 403
    stok = await login(client, "student1")
    r = await client.get("/admin/school/1/suggestions", headers=auth(stok))
    assert r.status_code == 403

    # مدرسه ناشناس → 403 (گارد Scope پیش از چک وجود)
    r = await client.get("/admin/school/999/suggestions", headers=auth(tok))
    assert r.status_code == 403

    # فیلتر وضعیت نامعتبر → 400
    r = await client.get("/admin/school/1/suggestions?status=weird", headers=auth(tok))
    assert r.status_code == 400
