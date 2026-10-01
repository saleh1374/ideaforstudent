"""آزمون‌های ثبت‌نام عمومی دانش‌آموز و پذیرش مدیر مدرسه (Feature B):
درخواستِ بدون کاربرِ ورودی → تأیید/رد → ساخت کاربر+پروفایل، گاردهای حوزه
manage_admissions، فهرست کلاس‌ها، افزودن مستقیم دانش‌آموز و حوزه جغرافیایی
/geo/me (Feature C)."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_daneshyar.db")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.db import AsyncSessionLocal, Base, engine
from app.main import app
from app.models.org import StudentProfile, User
from app.models.rbac import AuditLog, Permission, Role
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


async def user_id(username: str) -> int:
    async with AsyncSessionLocal() as s:
        return (await s.execute(select(User.id).where(User.username == username))).scalar_one()


async def register(client, username, password="secret123", school_id=1, **overrides):
    payload = {
        "username": username,
        "password": password,
        "full_name": "دانش‌آموز تازه",
        "grade": "grade_10",
        "school_id": school_id,
    }
    payload.update(overrides)
    return await client.post("/auth/register", json=payload)


# ------------------------- ثبت‌نام عمومی + تأیید با کلاس -------------------------


@pytest.mark.anyio
async def test_register_public_and_approval_flow(client, seeded):
    """ثبت‌نام عمومی بدون توکن → بدون ورود تا تأیید → تأیید با کلاس →
    ورود فوری + پروفایل درست + 409 برای تصمیم دوباره."""
    # فهرست مدارس برای انتخابگر — عمومی، بدون توکن
    r = await client.get("/public/schools")
    assert r.status_code == 200, r.text
    schools = r.json()
    assert len(schools) == 2
    assert {"id", "name", "school_type", "district_name"} <= set(schools[0])
    assert schools[0]["id"] == 1
    assert schools[0]["district_name"] == "ناحیه ۱ تهران"

    # ثبت‌نام موفق → درخواست pending
    r = await register(client, "newadmit")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["request_id"] > 0
    assert "تأیید مدیر مدرسه" in body["message_fa"]

    # پیش از تأیید: نه کاربری ساخته شده، نه ورود ممکن است
    async with AsyncSessionLocal() as s:
        assert (await s.execute(select(User.id).where(User.username == "newadmit"))).first() is None
    r = await client.post("/auth/login", json={"username": "newadmit", "password": "secret123"})
    assert r.status_code == 401

    # نام کاربری تکراری: با درخواست در انتظار و با کاربر موجود → 409
    r = await register(client, "newadmit")
    assert r.status_code == 409
    assert r.json()["detail"] == "نام کاربری قبلاً استفاده شده"
    r = await register(client, "student1")
    assert r.status_code == 409

    # اعتبارسنجی‌ها
    r = await register(client, "shortpwd", password="123")
    assert r.status_code == 400
    r = await register(client, "badgrade", grade="grade_99")
    assert r.status_code == 400
    r = await register(client, "badschool", school_id=999)
    assert r.status_code == 404
    r = await register(client, "bad name")
    assert r.status_code == 400

    # رویداد ممیزی: فقط ثبت‌نام‌های موفق
    async with AsyncSessionLocal() as s:
        rows = (
            await s.execute(
                select(AuditLog).where(AuditLog.action == "admission_submitted").order_by(AuditLog.id)
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].actor_user_id is None
        assert "username=newadmit" in (rows[0].detail or "")

    # مدیر مدرسه فهرست را می‌بیند
    stok = await login(client, "schooladmin")
    r = await client.get("/admin/admission-requests", headers=auth(stok))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total"] == 1
    row = data["requests"][0]
    assert {"id", "full_name", "username", "grade", "phone", "school_id", "school_name", "status", "created_at"} <= set(row)
    assert row["username"] == "newadmit"
    assert row["status"] == "pending"
    assert row["school_id"] == 1
    assert row["school_name"] == "دبیرستان نمونه دانشیار"
    req_id = row["id"]

    # تأیید با کلاس ۱
    r = await client.post(
        f"/admin/admission-requests/{req_id}/decide",
        headers=auth(stok),
        json={"approve": True, "class_id": 1},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"
    assert r.json()["class_id"] == 1

    # تصمیم دوباره → 409
    r = await client.post(
        f"/admin/admission-requests/{req_id}/decide", headers=auth(stok), json={"approve": True}
    )
    assert r.status_code == 409

    # اکنون ورود کار می‌کند و پروفایل درست است
    r = await client.post("/auth/login", json={"username": "newadmit", "password": "secret123"})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["role"] == "student"
    async with AsyncSessionLocal() as s:
        user = (await s.execute(select(User).where(User.username == "newadmit"))).scalar_one()
        assert user.is_active is True
        profile = (
            await s.execute(select(StudentProfile).where(StudentProfile.user_id == user.id))
        ).scalar_one()
        assert (profile.school_id, profile.class_id, profile.grade) == (1, 1, "grade_10")


# ------------------------- کلاس اشتباه، کلاس پیش‌فرض، رد -------------------------


@pytest.mark.anyio
async def test_approve_class_validation_and_default(client, seeded):
    """کلاس مدرسه دیگر → 400؛ کلاس ناموجود → 404؛ بدون class_id → نخستین
    کلاس مدرسه خودِ درخواست."""
    r = await register(client, "classcheck")
    req_id = r.json()["request_id"]
    stok = await login(client, "schooladmin")

    # کلاس ۳ متعلق به مدرسه ۲ است → 400
    r = await client.post(
        f"/admin/admission-requests/{req_id}/decide",
        headers=auth(stok),
        json={"approve": True, "class_id": 3},
    )
    assert r.status_code == 400, r.text
    assert "مدرسه" in r.json()["detail"]

    # کلاس ناموجود → 404
    r = await client.post(
        f"/admin/admission-requests/{req_id}/decide",
        headers=auth(stok),
        json={"approve": True, "class_id": 999},
    )
    assert r.status_code == 404

    # هنوز در انتظار است → بدون class_id خودکار نخستین کلاس مدرسه
    r = await client.get(
        "/admin/admission-requests", headers=auth(stok), params={"status": "pending"}
    )
    assert r.json()["total"] == 1
    r = await client.post(
        f"/admin/admission-requests/{req_id}/decide", headers=auth(stok), json={"approve": True}
    )
    assert r.status_code == 200, r.text
    assert r.json()["class_id"] == 1

    async with AsyncSessionLocal() as s:
        user = (await s.execute(select(User).where(User.username == "classcheck"))).scalar_one()
        profile = (
            await s.execute(select(StudentProfile).where(StudentProfile.user_id == user.id))
        ).scalar_one()
        assert (profile.school_id, profile.class_id) == (1, 1)


@pytest.mark.anyio
async def test_rejected_request_cannot_login(client, seeded):
    """رد درخواست → همچنان ورود ناممکن؛ وضعیت rejected در فهرست."""
    r = await register(client, "rejected1")
    req_id = r.json()["request_id"]
    stok = await login(client, "schooladmin")

    r = await client.post(
        f"/admin/admission-requests/{req_id}/decide", headers=auth(stok), json={"approve": False}
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "rejected"

    r = await client.post("/auth/login", json={"username": "rejected1", "password": "secret123"})
    assert r.status_code == 401
    async with AsyncSessionLocal() as s:
        assert (await s.execute(select(User.id).where(User.username == "rejected1"))).first() is None

    # تصمیم دوباره → 409
    r = await client.post(
        f"/admin/admission-requests/{req_id}/decide", headers=auth(stok), json={"approve": False}
    )
    assert r.status_code == 409

    # فیلتر وضعیت و اعتبارسنجی آن
    r = await client.get(
        "/admin/admission-requests", headers=auth(stok), params={"status": "rejected"}
    )
    assert r.json()["total"] == 1
    assert r.json()["requests"][0]["username"] == "rejected1"
    r = await client.get(
        "/admin/admission-requests", headers=auth(stok), params={"status": "bogus"}
    )
    assert r.status_code == 400

    # رویداد رد ثبت شده است
    async with AsyncSessionLocal() as s:
        rows = (
            await s.execute(select(AuditLog).where(AuditLog.action == "admission_rejected"))
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].actor_user_id == await user_id("schooladmin")


# ------------------------- گاردهای حوزه manage_admissions -------------------------


@pytest.mark.anyio
async def test_admission_scope_guards(client, seeded):
    """مدرسه‌دار فقط مدرسه خودش را می‌بیند؛ ناحیه/استان همه را (شامل بدون
    مدرسه)؛ معلم/دانش‌آموز بدون مجوز → 403؛ «مدیر مدرسه دیگر» → 403."""
    r = await register(client, "admitA", school_id=1)
    id_a = r.json()["request_id"]
    r = await register(client, "admitB", school_id=2)
    id_b = r.json()["request_id"]
    r = await register(client, "admitC", school_id=None)
    id_c = r.json()["request_id"]

    stok = await login(client, "schooladmin")
    dtok = await login(client, "districtadmin")
    ptok = await login(client, "provinceadmin")
    ttok = await login(client, "teacher1")
    sutok = await login(client, "student1")

    # مدیر مدرسه ۱: فقط مدرسه خودش (نه مدرسه ۲، نه بدون مدرسه)
    r = await client.get("/admin/admission-requests", headers=auth(stok))
    assert r.status_code == 200, r.text
    assert {row["username"] for row in r.json()["requests"]} == {"admitA"}

    # ناحیه و استان: هر سه
    for tok in (dtok, ptok):
        r = await client.get("/admin/admission-requests", headers=auth(tok))
        assert r.status_code == 200, r.text
        assert {row["username"] for row in r.json()["requests"]} == {"admitA", "admitB", "admitC"}

    # معلم/دانش‌آموز بدون manage_admissions → 403 (فهرست و تصمیم)
    for tok in (ttok, sutok):
        r = await client.get("/admin/admission-requests", headers=auth(tok))
        assert r.status_code == 403
        r = await client.post(
            f"/admin/admission-requests/{id_a}/decide", headers=auth(tok), json={"approve": True}
        )
        assert r.status_code == 403

    # «مدیر مدرسه دیگر»: teacher2 با manage_admissions در حوزه مدرسه ۲
    # (توسط مدیر ناحیه و با قاعده طلایی تفویض می‌شود)
    async with AsyncSessionLocal() as s:
        role = (await s.execute(select(Role).where(Role.key == "school_admin"))).scalar_one()
        perm = (
            await s.execute(select(Permission).where(Permission.key == "manage_admissions"))
        ).scalar_one()
    r = await client.post(
        "/admin/permissions/grant",
        headers=auth(dtok),
        json={
            "grantee_user_id": await user_id("teacher2"),
            "role_id": role.id,
            "permission_id": perm.id,
            "scope_type": "school",
            "scope_id": 2,
        },
    )
    assert r.status_code == 200, r.text
    t2tok = await login(client, "teacher2")

    # دید او فقط مدرسه ۲ است
    r = await client.get("/admin/admission-requests", headers=auth(t2tok))
    assert {row["username"] for row in r.json()["requests"]} == {"admitB"}

    # درخواست مدرسه ۱ → 403
    r = await client.post(
        f"/admin/admission-requests/{id_a}/decide", headers=auth(t2tok), json={"approve": True}
    )
    assert r.status_code == 403
    # درخواست بدون مدرسه (حوزه مدرسه، نه ناحیه) → 403
    r = await client.post(
        f"/admin/admission-requests/{id_c}/decide",
        headers=auth(t2tok),
        json={"approve": True, "school_id": 2},
    )
    assert r.status_code == 403
    # درخواست مدرسه خودش → 200
    r = await client.post(
        f"/admin/admission-requests/{id_b}/decide",
        headers=auth(t2tok),
        json={"approve": True, "class_id": 3},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"


@pytest.mark.anyio
async def test_null_school_request_decided_by_district(client, seeded):
    """درخواست بدون مدرسه: مدرسه‌دار نه می‌بیند نه تصمیم می‌گیرد؛ ناحیه با
    تعیین مدرسه تأیید می‌کند (بدون مدرسه → 400)."""
    r = await register(client, "noschool", school_id=None)
    req_id = r.json()["request_id"]
    stok = await login(client, "schooladmin")
    dtok = await login(client, "districtadmin")

    r = await client.get("/admin/admission-requests", headers=auth(stok))
    assert {row["username"] for row in r.json()["requests"]} == set()
    r = await client.post(
        f"/admin/admission-requests/{req_id}/decide",
        headers=auth(stok),
        json={"approve": True, "school_id": 1},
    )
    assert r.status_code == 403

    # ناحیه بدون تعیین مدرسه → 400
    r = await client.post(
        f"/admin/admission-requests/{req_id}/decide", headers=auth(dtok), json={"approve": True}
    )
    assert r.status_code == 400

    # ناحیه با مدرسه و کلاس → تأیید
    r = await client.post(
        f"/admin/admission-requests/{req_id}/decide",
        headers=auth(dtok),
        json={"approve": True, "school_id": 1, "class_id": 1},
    )
    assert r.status_code == 200, r.text
    assert r.json()["school_id"] == 1

    r = await client.post("/auth/login", json={"username": "noschool", "password": "secret123"})
    assert r.status_code == 200
    async with AsyncSessionLocal() as s:
        user = (await s.execute(select(User).where(User.username == "noschool"))).scalar_one()
        profile = (
            await s.execute(select(StudentProfile).where(StudentProfile.user_id == user.id))
        ).scalar_one()
        assert (profile.school_id, profile.class_id) == (1, 1)


# ------------------------- افزودن مستقیم دانش‌آموز + فهرست کلاس‌ها -------------------------


@pytest.mark.anyio
async def test_direct_student_creation(client, seeded):
    """POST /admin/students: ساخت فوری دانش‌آموز توسط مدیر مدرسه؛ تکراری →
    409؛ کلاس مدرسه دیگر → 403؛ بدون مجوز → 403."""
    stok = await login(client, "schooladmin")
    dtok = await login(client, "districtadmin")
    ttok = await login(client, "teacher1")
    sutok = await login(client, "student1")

    payload = {
        "username": "direct1",
        "password": "secret123",
        "full_name": "دانش‌آموز مستقیم",
        "grade": "grade_10",
        "class_id": 1,
    }

    # بدون manage_admissions → 403
    for tok in (ttok, sutok):
        r = await client.post("/admin/students", headers=auth(tok), json=payload)
        assert r.status_code == 403

    # مدیر مدرسه → 200
    r = await client.post("/admin/students", headers=auth(stok), json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["school_id"] == 1 and body["class_id"] == 1

    # ورود بلافاصله + پروفایل درست
    r = await client.post("/auth/login", json={"username": "direct1", "password": "secret123"})
    assert r.status_code == 200, r.text
    async with AsyncSessionLocal() as s:
        user = (await s.execute(select(User).where(User.username == "direct1"))).scalar_one()
        assert user.is_active is True and user.system_role == "student"
        profile = (
            await s.execute(select(StudentProfile).where(StudentProfile.user_id == user.id))
        ).scalar_one()
        assert (profile.school_id, profile.class_id, profile.grade) == (1, 1, "grade_10")

    # تکراری → 409
    r = await client.post("/admin/students", headers=auth(stok), json=payload)
    assert r.status_code == 409
    assert r.json()["detail"] == "نام کاربری قبلاً استفاده شده"

    # کلاس مدرسه دیگر → 403
    r = await client.post(
        "/admin/students", headers=auth(stok), json={**payload, "username": "direct2", "class_id": 3}
    )
    assert r.status_code == 403

    # رمز کوتاه → 400
    r = await client.post(
        "/admin/students",
        headers=auth(stok),
        json={**payload, "username": "direct3", "password": "12"},
    )
    assert r.status_code == 400

    # کلاس ناموجود → 404
    r = await client.post(
        "/admin/students", headers=auth(stok), json={**payload, "username": "direct4", "class_id": 999}
    )
    assert r.status_code == 404

    # رویداد ممیزی: فقط یک ساخت موفق
    async with AsyncSessionLocal() as s:
        rows = (
            await s.execute(select(AuditLog).where(AuditLog.action == "student_created"))
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].actor_user_id == await user_id("schooladmin")
        assert "school=1" in (rows[0].detail or "")

    # مدیر ناحیه کلاس هر دو مدرسه را دارد
    r = await client.post(
        "/admin/students", headers=auth(dtok), json={**payload, "username": "direct5", "class_id": 3}
    )
    assert r.status_code == 200, r.text
    assert r.json()["school_id"] == 2


@pytest.mark.anyio
async def test_school_classes_picker(client, seeded):
    """GET /admin/school/{id}/classes: فهرست کلاس‌ها با جمعیت — همان گارد
    حوزه مدرسه بقیه endpointهای مدرسه."""
    stok = await login(client, "schooladmin")
    dtok = await login(client, "districtadmin")

    r = await client.get("/admin/school/1/classes", headers=auth(stok))
    assert r.status_code == 200, r.text
    classes = r.json()
    assert [c["id"] for c in classes] == [1, 2]
    by_id = {c["id"]: c for c in classes}
    assert by_id[1]["students_count"] == 3  # student1..3 در کلاس ۱۰۱
    assert by_id[2]["students_count"] == 2  # student4,5 در کلاس ۱۰۲
    assert by_id[1]["grade"] == "grade_10"
    assert by_id[1]["capacity"] == 30
    assert by_id[1]["name"] == "۱۰۱"

    # مدرسه دیگر → 403؛ بدون توکن → 401
    r = await client.get("/admin/school/2/classes", headers=auth(stok))
    assert r.status_code == 403
    r = await client.get("/admin/school/1/classes")
    assert r.status_code == 401

    # مدرسه ناموجود → گاردِ حوزه (مانند بقیه endpointهای /admin/school/*)
    r = await client.get("/admin/school/999/classes", headers=auth(dtok))
    assert r.status_code == 403


# ------------------------- Feature C: حوزه تماس‌گیرنده -------------------------


@pytest.mark.anyio
async def test_geo_me_derives_scope(client, seeded):
    """GET /geo/me: استان/ناحیه تماس‌گیرنده از تخصیص مجوزها — پنل /province."""
    ptok = await login(client, "provinceadmin")
    dtok = await login(client, "districtadmin")
    stok = await login(client, "schooladmin")
    ttok = await login(client, "teacher1")

    r = await client.get("/geo/me", headers=auth(ptok))
    assert r.status_code == 200, r.text
    assert r.json() == {"province_id": 1, "district_id": None, "role": "province_admin"}

    r = await client.get("/geo/me", headers=auth(dtok))
    assert r.json() == {"province_id": 1, "district_id": 1, "role": "district_admin"}

    r = await client.get("/geo/me", headers=auth(stok))
    assert r.json() == {"province_id": 1, "district_id": 1, "role": "school_admin"}

    # معلم: بدون حوزه مجوز، از تخصیص مدرسه‌اش استخراج می‌شود
    r = await client.get("/geo/me", headers=auth(ttok))
    assert r.json() == {"province_id": 1, "district_id": 1, "role": "teacher"}

    # بدون توکن → 401
    r = await client.get("/geo/me")
    assert r.status_code == 401
