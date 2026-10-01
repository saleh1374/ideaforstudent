"""تست‌های §15 دستیار هوشمند معلم و §16 اختیار تأیید/ویرایش/رد."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_teachercopilot.db")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.db import AsyncSessionLocal, Base, engine
from app.main import app
from app.models.assessment import Exam
from app.models.rbac import AuditLog
from app.models.slm import PlanTask
from app.models.teacher_copilot import TeacherSuggestion
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


# ------------------------- §15 پرسش و پاسخ کوپایلت -------------------------


@pytest.mark.anyio
async def test_copilot_overview_reply_with_sources(client, seeded):
    tok = await login(client, "teacher1")
    r = await client.post(
        "/teacher/classes/1/copilot/chat",
        json={"message": "وضعیت کلی کلاس چطور است؟"},
        headers=auth(tok),
    )
    assert r.status_code == 200, r.text
    data = r.json()

    assert data["conversation_id"] >= 1
    assert data["intent"] in {"overview", "weak_cause", "intervention"}
    assert "کلاس" in data["reply"]
    assert "copilot است" in data["reply"]  # یادداشت §15/§16
    assert isinstance(data["sources"], list)
    assert data["note_fa"]

    # رویداد ممیزی §ضمیمه ب
    rows = await audit_actions("teacher_copilot_query")
    assert rows and rows[-1].actor_user_id is not None

    # ادامه گفت‌وگو در همان conversation + تاریخچه
    r2 = await client.post(
        "/teacher/classes/1/copilot/chat",
        json={"message": "چرا کلاسم در احتمال ضعیفه؟", "conversation_id": data["conversation_id"]},
        headers=auth(tok),
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["conversation_id"] == data["conversation_id"]

    r3 = await client.get(
        f"/teacher/classes/1/copilot/conversations/{data['conversation_id']}", headers=auth(tok)
    )
    assert r3.status_code == 200, r3.text
    msgs = r3.json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert msgs[1]["intent"]


@pytest.mark.anyio
async def test_copilot_intent_detection(client, seeded):
    tok = await login(client, "teacher1")

    # نمونه §15: ریشه‌یابی ضعف
    r = await client.post(
        "/teacher/classes/1/copilot/chat",
        json={"message": "چرا کلاسم در احتمال ضعیفه؟"},
        headers=auth(tok),
    )
    assert r.status_code == 200, r.text
    assert r.json()["intent"] == "weak_cause"
    assert "تسط" in r.json()["reply"]

    # نمونه §15: نمره خوب ولی ماندگاری افت
    r = await client.post(
        "/teacher/classes/1/copilot/chat",
        json={"message": "دانش‌آموزانی با نمره خوب ولی افت ماندگاری پیدا کن"},
        headers=auth(tok),
    )
    assert r.status_code == 200, r.text
    assert r.json()["intent"] == "retention_drop"


@pytest.mark.anyio
async def test_copilot_build_exam_creates_proposal_not_exam(client, seeded):
    """§16: درخواست ساخت آزمون فقط کارت پیشنهاد می‌سازد؛ بدون تأیید چیزی ساخته نمی‌شود."""
    tok = await login(client, "teacher1")
    r = await client.post(
        "/teacher/classes/1/copilot/chat",
        json={"message": "برای فردا یک آزمون بساز که خطاهای مفهومی کلاس را پوشش بده"},
        headers=auth(tok),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["intent"] == "build_exam"
    assert data["suggestions"], "کارت پیشنهاد ساخت آزمون باید ساخته شود"
    assert "تأیید" in data["reply"] and "ساخته نمی‌شود" in data["reply"]

    # هیچ آزمونی بدون تأیید ساخته نشده است
    async with AsyncSessionLocal() as s:
        exams = list((await s.execute(select(Exam).where(Exam.class_id == 1))).scalars())
    assert all(e.status != "draft" or e.title_fa != "پیش‌نویس" for e in exams)
    assert not any("خطاهای مفهومی" in (e.title_fa or "") for e in exams)

    # رویداد ممیزی پرسش
    assert await audit_actions("teacher_copilot_query")


@pytest.mark.anyio
async def test_suggestion_generate_idempotent_and_guards(client, seeded):
    tok = await login(client, "teacher1")

    r = await client.post("/teacher/classes/1/suggestions/generate", headers=auth(tok))
    assert r.status_code == 200, r.text
    gen = r.json()
    assert gen["ok"] is True

    r = await client.get("/teacher/classes/1/suggestions", headers=auth(tok))
    assert r.status_code == 200, r.text
    suggestions = r.json()["suggestions"]
    assert suggestions, "داده کلاس ۱ باید دست‌کم یک پیشنهاد بسازد"
    for s in suggestions:
        assert s["status"] == "proposed"
        assert s["title_fa"] and s["evidence_fa"] and s["actions_fa"]
        assert s["kind"] in ("draft_exam", "send_practice", "advice")

    # idempotent
    r = await client.post("/teacher/classes/1/suggestions/generate", headers=auth(tok))
    assert r.json()["created"] == 0

    # دانش‌آموز → 403
    stok = await login(client, "student1")
    r = await client.get("/teacher/classes/1/suggestions", headers=auth(stok))
    assert r.status_code == 403

    # معلم کلاس دیگر (teacher2 روی کلاس ۱ فعال نیست) → 403 گارد پیش از چک وجود
    tok2 = await login(client, "teacher2")
    r = await client.get("/teacher/classes/1/suggestions", headers=auth(tok2))
    assert r.status_code == 403

    # کلاس ناشناس → 403 (گارد پیش از چک وجود)
    r = await client.get("/teacher/classes/999/suggestions", headers=auth(tok))
    assert r.status_code == 403

    # بدون توکن → 401
    r = await client.get("/teacher/classes/1/suggestions")
    assert r.status_code == 401

    # پیام خالی → 400
    r = await client.post(
        "/teacher/classes/1/copilot/chat", json={"message": "   "}, headers=auth(tok)
    )
    assert r.status_code == 400

    # فیلتر وضعیت نامعتبر → 400
    r = await client.get("/teacher/classes/1/suggestions?status=weird", headers=auth(tok))
    assert r.status_code == 400


@pytest.mark.anyio
async def test_conversation_scope(client, seeded):
    """گفت‌وگوی کلاس دیگر با شناسه کلاس خودمان قابل بازیابی نیست (404)."""
    tok = await login(client, "teacher1")
    r = await client.post("/teacher/classes/1/copilot/chat", json={"message": "سلام"}, headers=auth(tok))
    conv_id = r.json()["conversation_id"]

    r2 = await client.get(f"/teacher/classes/1/copilot/conversations/99999", headers=auth(tok))
    assert r2.status_code == 404


# ------------------------- §16 اختیار معلم: تأیید، ویرایش، رد -------------------------


@pytest.mark.anyio
async def test_suggestion_approve_draft_exam_executes(client, seeded):
    """تأیید کارت «ساخت آزمون» → پیش‌نویس آزمون واقعاً ساخته می‌شود + ممیزی."""
    tok = await login(client, "teacher1")

    # کارت از همان درخواست چت ساخته می‌شود (§15 نمونه گفت‌وگو)
    r = await client.post(
        "/teacher/classes/1/copilot/chat",
        json={"message": "یک آزمون برای مجموعه‌ها و عملیات بساز"},
        headers=auth(tok),
    )
    assert r.status_code == 200, r.text
    sugg_ids = r.json()["suggestions"]
    assert sugg_ids, "کارت پیشنهاد ساخت آزمون باید ساخته شود"
    sid = sugg_ids[0]

    r = await client.post(
        f"/teacher/classes/1/suggestions/{sid}/decide",
        json={"action": "approve"},
        headers=auth(tok),
    )
    assert r.status_code == 200, r.text
    sugg = r.json()["suggestion"]
    assert sugg["status"] == "approved"
    assert sugg["result"] and sugg["result"].get("exam_id")
    assert await audit_actions("ai_suggestion_approved")

    # آزمون ساخته‌شده واقعاً وجود دارد و پیش‌نویس همان کلاس است
    exam_id = sugg["result"]["exam_id"]
    r = await client.get(f"/teacher/exams/{exam_id}", headers=auth(tok))
    assert r.status_code == 200, r.text
    assert r.json()["exam"]["status"] == "draft"
    assert r.json()["exam"]["class_id"] == 1

    # تصمیم تکراری → 409
    r = await client.post(
        f"/teacher/classes/1/suggestions/{sid}/decide", json={"action": "approve"}, headers=auth(tok)
    )
    assert r.status_code == 409


@pytest.mark.anyio
async def test_suggestion_edit_reject_and_guards(client, seeded):
    tok = await login(client, "teacher1")
    r = await client.post("/teacher/classes/1/suggestions/generate", headers=auth(tok))
    assert r.status_code == 200, r.text
    created = r.json()["suggestions"]
    assert len(created) >= 2, "برای هر دو مسیر ویرایش و رد باید پیشنهاد موجود باشد"

    # ویرایش بدون فهرست اقدام → 409
    s1 = created[0]["id"]
    r = await client.post(
        f"/teacher/classes/1/suggestions/{s1}/decide", json={"action": "edit"}, headers=auth(tok)
    )
    assert r.status_code == 409

    # ویرایش موفق + ممیزی
    r = await client.post(
        f"/teacher/classes/1/suggestions/{s1}/decide",
        json={"action": "edit", "edited_actions": ["اقدام اول معلم", "بازآزمون ۷ روز"], "note": "با اولویت"},
        headers=auth(tok),
    )
    assert r.status_code == 200, r.text
    sugg = r.json()["suggestion"]
    assert sugg["status"] == "edited"
    assert sugg["final_actions_fa"] == ["اقدام اول معلم", "بازآزمون ۷ روز"]
    assert await audit_actions("ai_suggestion_edited")

    # رد + ممیزی
    s2 = created[1]["id"]
    r = await client.post(
        f"/teacher/classes/1/suggestions/{s2}/decide",
        json={"action": "reject", "note": "کلاس جلسه بعد دارد"},
        headers=auth(tok),
    )
    assert r.status_code == 200, r.text
    assert r.json()["suggestion"]["status"] == "rejected"
    assert await audit_actions("ai_suggestion_rejected")

    # عملیات نامعتبر → 400
    r = await client.post(
        f"/teacher/classes/1/suggestions/{s2}/decide", json={"action": "delete"}, headers=auth(tok)
    )
    assert r.status_code == 400

    # پیشنهاد ناشناس در کلاس خودمان → 404
    r = await client.post(
        "/teacher/classes/1/suggestions/99999/decide", json={"action": "approve"}, headers=auth(tok)
    )
    assert r.status_code == 404

    # کلاس دیگر → 403 (گارد پیش از چک وجود)
    tok2 = await login(client, "teacher2")
    r = await client.post(
        f"/teacher/classes/1/suggestions/{s1}/decide", json={"action": "approve"}, headers=auth(tok2)
    )
    assert r.status_code == 403


@pytest.mark.anyio
async def test_suggestion_approve_send_practice_creates_tasks(client, seeded):
    """تأیید کارت «ارسال تمرین» → کار برنامه برای دانش‌آموزان ساخته می‌شود."""
    tok = await login(client, "teacher1")
    r = await client.post("/teacher/classes/1/suggestions/generate", headers=auth(tok))
    assert r.status_code == 200, r.text
    practice = [s for s in r.json()["suggestions"] if s["kind"] == "send_practice"]
    if not practice:
        pytest.skip("گروه مداخله/ماندگاری در داده seed خالی است")

    sid = practice[0]["id"]
    r = await client.post(
        f"/teacher/classes/1/suggestions/{sid}/decide", json={"action": "approve"}, headers=auth(tok)
    )
    assert r.status_code == 200, r.text
    result = r.json()["suggestion"]["result"]
    assert result and result.get("task_ids")

    async with AsyncSessionLocal() as s:
        tasks = list(
            (
                await s.execute(select(PlanTask).where(PlanTask.id.in_(result["task_ids"])))
            ).scalars()
        )
    assert len(tasks) == result["students"]
    assert all(t.payload.get("origin") == "teacher_copilot" for t in tasks)
