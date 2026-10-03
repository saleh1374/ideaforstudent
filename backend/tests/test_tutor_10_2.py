"""§10.2 بازار معلم خصوصی: تأیید صالحیت، رضایت والد، مهلت ۷۲ ساعته،
کارت جلسه/حضور/امتیاز و کد دعوت امن."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_daneshyar_tutor102.db")

import pytest
from datetime import datetime, timedelta
from httpx import ASGITransport, AsyncClient

from app.core.db import AsyncSessionLocal, Base, engine
from app.main import app
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


async def user_id(client, username):
    tok = await login(client, username)
    r = await client.get("/auth/me", headers=auth(tok))
    assert r.status_code == 200, r.text
    return r.json()["id"], tok


# ------------------------- تأیید صالحیت (§10.2-۲/س) -------------------------


@pytest.mark.anyio
async def test_verification_flow(client, seeded):
    ttok = await login(client, "tutor1")

    # هنوز فرمی ثبت نشده
    r = await client.get("/tutor/verification", headers=auth(ttok))
    assert r.status_code == 200
    assert r.json()["status"] == "none"

    # ارسال ناقص → فهرست موارد لازم
    r = await client.post("/tutor/verification", headers=auth(ttok), json={"degree": "کارشناسی"})
    assert r.status_code == 400
    assert "معرفی" in r.json()["detail"]

    # تکمیل و ارسال
    r = await client.post(
        "/tutor/verification",
        headers=auth(ttok),
        json={
            "full_name": "علی رضایی",
            "national_id": "0084575946",
            "degree": "کارشناسی ارشد ریاضی",
            "university": "دانشگاه تهران",
            "experience_years": 8,
            "intro": "۸ سال تدریس ریاضی دوره متوسطه",
            "accepts_under18": True,
            "police_clearance": True,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "submitted"

    # کد ملی متن ساده ذخیره نشده است (§18)
    from app.models.tutoring import TutorVerification
    from sqlalchemy import select

    async with AsyncSessionLocal() as session:
        ver = (await session.execute(select(TutorVerification))).scalars().one()
    assert ver.national_id_hash and "0084575946" not in ver.national_id_hash
    assert ver.national_id_masked.endswith("946")

    # معلم عادی نمی‌تواند صف بررسی ببیند
    r = await client.get("/tutor/verifications/pending", headers=auth(ttok))
    assert r.status_code == 403

    # استان: صف را می‌بیند و تأیید می‌کند
    ptok = await login(client, "provinceadmin")
    r = await client.get("/tutor/verifications/pending", headers=auth(ptok))
    assert r.status_code == 200, r.text
    queue = r.json()["verifications"]
    assert len(queue) == 1 and queue[0]["status"] == "submitted"

    vid = queue[0]["id"]
    r = await client.post(
        f"/tutor/verifications/{vid}/decide",
        headers=auth(ptok),
        json={"decision": "verified", "note": "مدارک بررسی شد"},
    )
    assert r.status_code == 200, r.text

    # وضعیت معلم + نشان «تأییدشده» در بازار
    r = await client.get("/tutor/verification", headers=auth(ttok))
    assert r.json()["status"] == "verified"

    stok = await login(client, "student1")
    r = await client.get("/tutor/market", headers=auth(stok))
    row = next(t for t in r.json()["tutors"] if t["user_id"] != 0 and t["name"] == "معلم خصوصی ریاضی")
    assert row["verified"] is True

    # تأییدشده → قابل ویرایش نیست
    r = await client.post("/tutor/verification", headers=auth(ttok), json={"degree": "دکتری"})
    assert r.status_code == 400


@pytest.mark.anyio
async def test_rejected_tutor_cannot_take_students(client, seeded):
    ttok = await login(client, "tutor1")
    await client.post(
        "/tutor/verification",
        headers=auth(ttok),
        json={
            "full_name": "علی رضایی",
            "national_id": "0084575946",
            "degree": "کارشناسی",
            "intro": "معرفی",
        },
    )
    ptok = await login(client, "provinceadmin")
    vid = (await client.get("/tutor/verifications/pending", headers=auth(ptok))).json()["verifications"][0]["id"]
    r = await client.post(
        f"/tutor/verifications/{vid}/decide", headers=auth(ptok), json={"decision": "rejected"}
    )
    assert r.status_code == 200

    stok = await login(client, "student1")
    tutors = (await client.get("/tutor/market", headers=auth(stok))).json()["tutors"]
    tutor_id = next(t["user_id"] for t in tutors if t["name"] == "معلم خصوصی ریاضی")
    r = await client.post(
        "/tutor/requests",
        headers=auth(stok),
        json={"tutor_user_id": tutor_id, "subject": "math"},
    )
    assert r.status_code == 400
    assert "تأیید نشده" in r.json()["detail"]


# ------------------------- مهلت ۷۲ ساعته (§10.2-۶) -------------------------


@pytest.mark.anyio
async def test_request_expires_after_72h(client, seeded):
    stok = await login(client, "student1")
    tutors = (await client.get("/tutor/market", headers=auth(stok))).json()["tutors"]
    tutor_id = next(t["user_id"] for t in tutors if t["name"] == "معلم خصوصی ریاضی")

    r = await client.post(
        "/tutor/requests",
        headers=auth(stok),
        json={"tutor_user_id": tutor_id, "subject": "math"},
    )
    req_id = r.json()["request_id"]

    # والد تأیید می‌کند تا درخواست به معلم برسد
    ptok = await login(client, "parent1")
    await client.post(f"/tutor/requests/{req_id}/consent", headers=auth(ptok), json={"approve": True})

    # ساخت مصنوعی ۷۳ ساعت قبل
    from app.models.tutoring import TutorRequest

    async with AsyncSessionLocal() as session:
        req = await session.get(TutorRequest, req_id)
        req.created_at = datetime.utcnow() - timedelta(hours=73)
        await session.commit()

    stok2 = await login(client, "student1")
    mine = (await client.get("/tutor/requests", headers=auth(stok2))).json()["requests"]
    row = next(x for x in mine if x["id"] == req_id)
    assert row["state"] == "expired"
    assert row["hours_left"] == 0

    # معلم دیگر نمی‌تواند پاسخ دهد
    ttok = await login(client, "tutor1")
    r = await client.post(f"/tutor/requests/{req_id}/decide", headers=auth(ttok), json={"approve": True})
    assert r.status_code == 400
    assert "منقضی" in r.json()["detail"]


# ------------------------- کارت جلسه، حضور، امتیاز (§10.2-۸/۹) -------------------------


@pytest.mark.anyio
async def test_session_card_attend_confirm_feedback(client, seeded):
    ttok = await login(client, "tutor1")
    stok = await login(client, "student1")
    student_uid, _ = await user_id(client, "student1")

    # لینک غیرمجاز رد می‌شود
    r = await client.post(
        "/tutor/sessions",
        headers=auth(ttok),
        json={
            "student_user_id": student_uid,
            "starts_at": "2026-10-05T16:00:00",
            "topic": "فصل ۳ — مشتق",
            "join_link": "https://example.com/room",
        },
    )
    assert r.status_code == 400
    assert "مجاز" in r.json()["detail"]

    # ثبت درست کارت جلسه
    r = await client.post(
        "/tutor/sessions",
        headers=auth(ttok),
        json={
            "student_user_id": student_uid,
            "starts_at": "2026-10-05T16:00:00",
            "duration_min": 60,
            "topic": "فصل ۳ — مشتق",
            "join_link": "https://meet.google.com/abc-defg-hij",
        },
    )
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]

    # دانش‌آموز جلسه را می‌بیند و حضور ثبت می‌کند
    sessions = (await client.get("/tutor/sessions", headers=auth(stok))).json()["sessions"]
    assert any(s["id"] == sid for s in sessions)
    assert next(s for s in sessions if s["id"] == sid)["attended"] is False

    r = await client.post(f"/tutor/sessions/{sid}/attend", headers=auth(stok))
    assert r.status_code == 200, r.text

    # معلم تأیید + یادداشت و تکلیف
    r = await client.post(f"/tutor/sessions/{sid}/confirm", headers=auth(ttok))
    assert r.status_code == 200, r.text
    r = await client.post(
        f"/tutor/sessions/{sid}/note",
        headers=auth(ttok),
        json={"note": "قواعد مشتق مرور شد", "homework": "تمرین ۳–۵ صفحه ۴۲"},
    )
    assert r.status_code == 200, r.text

    # امتیاز دانش‌آموز
    r = await client.post(
        f"/tutor/sessions/{sid}/feedback", headers=auth(stok), json={"rating": 5, "comment": "عالی"}
    )
    assert r.status_code == 200, r.text

    # امتیاز نامعتبر
    r = await client.post(f"/tutor/sessions/{sid}/feedback", headers=auth(stok), json={"rating": 9})
    assert r.status_code == 400

    # دانش‌آموز دیگر نمی‌تواند برای جلسه دیگران امتیاز بدهد
    other = await login(client, "student2")
    r = await client.post(f"/tutor/sessions/{sid}/feedback", headers=auth(other), json={"rating": 1})
    assert r.status_code == 400

    sessions = (await client.get("/tutor/sessions", headers=auth(stok))).json()["sessions"]
    row = next(s for s in sessions if s["id"] == sid)
    assert row["attended"] is True and row["tutor_confirmed"] is True
    assert row["lesson_note"] and row["homework"]
    assert row["rating"] == 5 and row["rating_avg"] == 5

    # معلم هم می‌بیند
    sessions = (await client.get("/tutor/sessions", headers=auth(ttok))).json()["sessions"]
    assert any(s["id"] == sid for s in sessions)


@pytest.mark.anyio
async def test_tutor_cannot_confirm_others_session(client, seeded):
    ttok = await login(client, "tutor1")
    student_uid, _ = await user_id(client, "student1")
    r = await client.post(
        "/tutor/sessions",
        headers=auth(ttok),
        json={"student_user_id": student_uid, "starts_at": "2026-10-05T16:00:00", "topic": "آزمایشی"},
    )
    sid = r.json()["session_id"]

    # teacher2 معلم این جلسه نیست
    t2 = await login(client, "teacher2")
    r = await client.post(f"/tutor/sessions/{sid}/confirm", headers=auth(t2))
    assert r.status_code == 400
    r = await client.post(
        f"/tutor/sessions/{sid}/note", headers=auth(t2), json={"note": "دستکاری"}
    )
    assert r.status_code == 400


# ------------------------- کد دعوت امن + سقف گروه (§10.2-۵) -------------------------


@pytest.mark.anyio
async def test_invite_code_and_group_cap(client, seeded):
    ttok = await login(client, "tutor1")
    stok = await login(client, "student1")

    r = await client.post(
        "/tutor/groups", headers=auth(ttok), json={"title": "کلاس گروهی ریاضی", "subject": "math"}
    )
    gid = r.json()["group_id"]

    # کد دعوت فقط برای مالک گروه
    other = await login(client, "student2")
    r = await client.post(f"/tutor/groups/{gid}/invites", headers=auth(other))
    assert r.status_code == 400

    r = await client.post(f"/tutor/groups/{gid}/invites", headers=auth(ttok))
    assert r.status_code == 200, r.text
    code = r.json()["code"]
    assert len(code) == 6

    # کد غلط رد می‌شود
    r = await client.post("/tutor/invites/join", headers=auth(stok), json={"code": "XXXXXX"})
    assert r.status_code == 400

    # عضویت با کد درست
    r = await client.post("/tutor/invites/join", headers=auth(stok), json={"code": code})
    assert r.status_code == 200 and r.json()["ok"] is True

    # سقف ۶ نفر: ۵ نفر دیگر می‌پیوندند، نفر هفتم رد می‌شود
    for name in ["s2student1", "s2student2", "s2student3", "s2student4", "s2student5"]:
        tok = await login(client, name)
        r = await client.post("/tutor/invites/join", headers=auth(tok), json={"code": code})
        assert r.status_code == 200, r.text
    tok = await login(client, "s2student6")
    r = await client.post("/tutor/invites/join", headers=auth(tok), json={"code": code})
    assert r.status_code == 400
    assert "سقف" in r.json()["detail"]
