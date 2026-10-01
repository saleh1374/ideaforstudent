"""آزمون‌های پنل مدیر ناحیه (district spec §1–§4, §12, §15, §33): گارد
حوزه ناحیه، فهرست/ثبت/ویرایش مدرسه، انتصاب مدیر، کارکنان ناحیه، نمای
کلان و صندوق درخواست‌های استخدامِ فیلترشده بر اساس ناحیه."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_daneshyar.db")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.db import AsyncSessionLocal, Base, engine
from app.main import app
from app.models.employment import EmploymentRequest
from app.models.org import District, School, SchoolAssignment, User
from app.models.rbac import AuditLog
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


async def one(db, model, **filters):
    return (await db.execute(select(model).filter_by(**filters))).scalar_one()


async def user_id(username: str) -> int:
    async with AsyncSessionLocal() as s:
        return (await one(s, User, username=username)).id


async def audit_rows(action: str) -> list[tuple[int | None, str | None]]:
    async with AsyncSessionLocal() as s:
        rows = (
            await s.execute(select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.id))
        ).scalars().all()
        return [(r.actor_user_id, r.detail) for r in rows]


async def outside_school() -> int:
    """مدرسه‌ای در ناحیه دیگر — برای بررسی ایزوله‌بودن حوزه ناحیه."""
    async with AsyncSessionLocal() as s:
        district = District(province_id=1, name="ناحیه ۲ تهران")
        s.add(district)
        await s.flush()
        school = School(
            district_id=district.id,
            province_id=1,
            name="مدرسه خارج از ناحیه",
            school_code="S-9001",
            school_type="high_school",
            ownership_type="private",
        )
        s.add(school)
        await s.commit()
        return school.id


# ------------------------- §33 گارد حوزه ناحیه -------------------------


@pytest.mark.anyio
async def test_district_scope_gate(client, seeded):
    """«نقش بدون محدوده معنا ندارد»: فقط دارنده مجوز در حوزه ناحیه وارد
    پنل می‌شود؛ استان/مدرسه بدون حوزه ناحیه → 403."""
    dtok = await login(client, "districtadmin")
    stok = await login(client, "schooladmin")
    ptok = await login(client, "provinceadmin")

    r = await client.get("/district/me/schools", headers=auth(dtok))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["district"]["id"] == 1
    assert body["district"]["name"] == "ناحیه ۱ تهران"
    assert body["total"] == 2
    by_code = {row["school_code"]: row for row in body["schools"]}
    assert set(by_code) == {"S-1001", "S-1002"}

    # قاعده حداقل جمعیت ۱۰
    assert by_code["S-1001"]["suppressed"] is True
    assert by_code["S-1002"]["suppressed"] is False
    assert by_code["S-1001"]["principal"]["full_name"] == "مدیر مدرسه"

    # فیلتر وضعیت و جست‌وجو
    r = await client.get("/district/me/schools", headers=auth(dtok), params={"status": "active"})
    assert r.json()["total"] == 2
    r = await client.get("/district/me/schools", headers=auth(dtok), params={"search": "S-1002"})
    assert r.json()["total"] == 1
    assert r.json()["schools"][0]["school_code"] == "S-1002"

    # مدیر مدرسه حوزه ناحیه ندارد → 403
    r = await client.get("/district/me/schools", headers=auth(stok))
    assert r.status_code == 403

    # مدیر کل استان حوزه ناحیه ندارد → 403 (عمدی — district spec §33)
    r = await client.get("/district/me/schools", headers=auth(ptok))
    assert r.status_code == 403

    # بدون توکن → 401
    r = await client.get("/district/me/schools")
    assert r.status_code == 401


# ------------------------- §4 مدارس ناحیه -------------------------


@pytest.mark.anyio
async def test_register_and_patch_schools(client, seeded):
    dtok = await login(client, "districtadmin")

    # کد تکراری → 400
    r = await client.post(
        "/district/schools",
        headers=auth(dtok),
        json={
            "school_code": "S-1001",
            "name": "تکراری",
            "school_type": "high_school",
            "ownership_type": "private",
        },
    )
    assert r.status_code == 400

    # کد خالی → 400
    r = await client.post(
        "/district/schools",
        headers=auth(dtok),
        json={
            "school_code": "   ",
            "name": "بدون کد",
            "school_type": "high_school",
            "ownership_type": "private",
        },
    )
    assert r.status_code == 400

    # ثبت موفق + رویداد ممیزی
    r = await client.post(
        "/district/schools",
        headers=auth(dtok),
        json={
            "school_code": "S-2001",
            "name": "دبیرستان ناحیه ۱ — واحد ۲",
            "school_type": "high_school",
            "ownership_type": "private",
            "address": "خیابان آزادی",
        },
    )
    assert r.status_code == 200, r.text
    school_id = r.json()["school"]["id"]
    assert r.json()["school"]["status"] == "active"
    assert r.json()["school"]["id"] != 1
    registered = await audit_rows("school_registered")
    assert len(registered) == 1
    assert registered[0][0] == await user_id("districtadmin")

    r = await client.get("/district/me/schools", headers=auth(dtok))
    assert r.json()["total"] == 3

    # تغییر وضعیت
    r = await client.patch(
        f"/district/schools/{school_id}", headers=auth(dtok), json={"status": "inactive"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["school"]["status"] == "inactive"

    # وضعیت نامعتبر → 400
    r = await client.patch(
        f"/district/schools/{school_id}", headers=auth(dtok), json={"status": "closed"}
    )
    assert r.status_code == 400

    # نام خالی → 400
    r = await client.patch(
        f"/district/schools/{school_id}", headers=auth(dtok), json={"name": "  "}
    )
    assert r.status_code == 400

    # مدرسه خارج از ناحیه → 404
    other_id = await outside_school()
    r = await client.patch(
        f"/district/schools/{other_id}", headers=auth(dtok), json={"status": "inactive"}
    )
    assert r.status_code == 404

    # ناحیه‌ای غیر از ناحیه تماس‌گیرنده دیده نمی‌شود
    r = await client.get("/district/me/schools", headers=auth(dtok), params={"search": "S-9001"})
    assert r.json()["total"] == 0


# ------------------------- §2 نمای کلان -------------------------


@pytest.mark.anyio
async def test_district_overview_aggregates_only(client, seeded):
    dtok = await login(client, "districtadmin")

    r = await client.get("/district/overview", headers=auth(dtok))
    assert r.status_code == 200, r.text
    ov = r.json()
    assert ov["district"] == {"id": 1, "name": "ناحیه ۱ تهران"}
    assert ov["schools_count"] == 2
    assert ov["students_count"] == 15
    assert ov["classes_count"] == 3
    assert ov["teachers_count"] >= 2
    assert ov["pending_employment_requests"] == 0

    # تجمیع ناحیه بالای حداقل جمعیت است → اعداد نمایش داده می‌شوند
    assert ov["educational"]["suppressed"] is False
    assert ov["educational"]["avg_mastery"] is not None
    assert ov["worst_topics"]
    assert "حداقل" in ov["note_fa"]

    # بدون حوزه ناحیه → 403
    stok = await login(client, "schooladmin")
    r = await client.get("/district/overview", headers=auth(stok))
    assert r.status_code == 403


# ------------------------- §12 کارکنان ناحیه -------------------------


@pytest.mark.anyio
async def test_district_staff_management(client, seeded):
    dtok = await login(client, "districtadmin")

    r = await client.get("/district/staff", headers=auth(dtok))
    assert r.status_code == 200, r.text
    assert r.json()["district_id"] == 1
    assert "districtadmin" in {row["username"] for row in r.json()["staff"]}

    # نقش نامعتبر → 400
    r = await client.post(
        "/district/staff",
        headers=auth(dtok),
        json={
            "username": "badrole",
            "password": "secret123",
            "full_name": "نقش نامعتبر",
            "role": "school_admin",
        },
    )
    assert r.status_code == 400

    # رمز کوتاه → 400
    r = await client.post(
        "/district/staff",
        headers=auth(dtok),
        json={"username": "shortpass", "password": "123", "full_name": "کوتاه", "role": "teacher"},
    )
    assert r.status_code == 400

    # کارمند بدون بسته مجوز
    r = await client.post(
        "/district/staff",
        headers=auth(dtok),
        json={
            "username": "staff1",
            "password": "secret123",
            "full_name": "کارشناس ناحیه",
            "role": "district_staff",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["granted"] == []

    r = await client.post("/auth/login", json={"username": "staff1", "password": "secret123"})
    assert r.status_code == 200
    staff_tok = r.json()["token"]
    r = await client.get("/district/overview", headers=auth(staff_tok))
    assert r.status_code == 403  # بدون مجوز view_district_analytics

    # ساخت مدیر ناحیه جدید → بسته مجوز پیش‌فرض + رویداد district_admin_assigned
    r = await client.post(
        "/district/staff",
        headers=auth(dtok),
        json={
            "username": "newdistrictadmin",
            "password": "secret123",
            "full_name": "مدیر ناحیه دوم",
            "role": "district_admin",
        },
    )
    assert r.status_code == 200, r.text
    granted = r.json()["granted"]
    assert "view_district_analytics" in granted
    assert "manage_schools" in granted
    assert "manage_employment_policy" in granted

    assigned = await audit_rows("district_admin_assigned")
    assert len(assigned) == 1
    assert assigned[0][0] == await user_id("districtadmin")
    assert assigned[0][1] and "district=1" in assigned[0][1]

    r = await client.post("/auth/login", json={"username": "newdistrictadmin", "password": "secret123"})
    assert r.status_code == 200
    new_tok = r.json()["token"]
    r = await client.get("/district/overview", headers=auth(new_tok))
    assert r.status_code == 200, r.text
    r = await client.get("/district/me/schools", headers=auth(new_tok))
    assert r.status_code == 200, r.text

    # نام کاربری تکراری → 400
    r = await client.post(
        "/district/staff",
        headers=auth(dtok),
        json={
            "username": "newdistrictadmin",
            "password": "secret123",
            "full_name": "تکراری",
            "role": "district_admin",
        },
    )
    assert r.status_code == 400

    # قاعده طلایی: مجوزی که سازنده خودش ندارد → 403 و کاربر ساخته نمی‌شود
    r = await client.post(
        "/district/staff",
        headers=auth(dtok),
        json={
            "username": "ghostadmin",
            "password": "secret123",
            "full_name": "نفوذی",
            "role": "district_staff",
            "permission_keys": ["view_province_analytics"],
        },
    )
    assert r.status_code == 403, r.text
    denied = await audit_rows("delegation_denied_insufficient_owner_permission")
    assert any(d and "view_province_analytics" in d for _, d in denied)
    r = await client.post("/auth/login", json={"username": "ghostadmin", "password": "secret123"})
    assert r.status_code == 401

    # فهرست کارکنان
    r = await client.get("/district/staff", headers=auth(dtok))
    assert r.status_code == 200
    rows = {row["username"]: row for row in r.json()["staff"]}
    assert {"districtadmin", "staff1", "newdistrictadmin"} <= set(rows)
    assert rows["newdistrictadmin"]["system_role"] == "district_admin"
    assert rows["newdistrictadmin"]["employment"]["organization"] == "district"
    assert rows["newdistrictadmin"]["employment"]["status"] == "active"


# ------------------------- §15 انتصاب مدیر مدرسه -------------------------


@pytest.mark.anyio
async def test_principal_appointment_changes_assignment(client, seeded):
    dtok = await login(client, "districtadmin")
    teacher2 = await user_id("teacher2")
    schooladmin = await user_id("schooladmin")

    # کاربر ناموجود → 404
    r = await client.post(
        "/district/schools/1/principal", headers=auth(dtok), json={"user_id": 99999}
    )
    assert r.status_code == 404

    r = await client.post(
        "/district/schools/1/principal", headers=auth(dtok), json={"user_id": teacher2}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["changed"] is True
    assert body["principal_user_id"] == teacher2

    changed = await audit_rows("principal_changed")
    assigned = await audit_rows("principal_assigned")
    assert len(changed) == 1
    assert f"old_user={schooladmin}" in (changed[0][1] or "")
    assert len(assigned) == 1

    async with AsyncSessionLocal() as s:
        rows = (
            await s.execute(
                select(SchoolAssignment).where(
                    SchoolAssignment.school_id == 1, SchoolAssignment.role == "principal"
                )
            )
        ).scalars().all()
        active = [a for a in rows if a.status == "active"]
        ended = [a for a in rows if a.status == "ended"]
        assert len(active) == 1 and active[0].employee_id is not None
        assert len(ended) == 1 and ended[0].end_date is not None

    # فهرست مدارس مدیر جدید را نشان می‌دهد
    r = await client.get("/district/me/schools", headers=auth(dtok))
    s1 = next(row for row in r.json()["schools"] if row["school_code"] == "S-1001")
    assert s1["principal"]["user_id"] == teacher2

    # انتصاب مجدد همان کاربر → بدون تغییر و بدون رویداد اضافه
    r = await client.post(
        "/district/schools/1/principal", headers=auth(dtok), json={"user_id": teacher2}
    )
    assert r.status_code == 200
    assert r.json()["changed"] is False
    assert len(await audit_rows("principal_changed")) == 1

    # مدرسه خارج از ناحیه → 404
    other_id = await outside_school()
    r = await client.post(
        f"/district/schools/{other_id}/principal", headers=auth(dtok), json={"user_id": teacher2}
    )
    assert r.status_code == 404


# ------------------------- §33 صندوق استخدام ناحیه -------------------------


@pytest.mark.anyio
async def test_district_employment_inbox_is_filtered(client, seeded):
    dtok = await login(client, "districtadmin")
    stok = await login(client, "schooladmin")
    newteacher = await user_id("newteacher")
    schooladmin = await user_id("schooladmin")

    r = await client.post(
        "/admin/employment-requests",
        headers=auth(stok),
        json={
            "school_id": 1,
            "employee_user_id": newteacher,
            "full_name": "معلم ناحیه",
            "employment_type": "contractual",
            "organization": "government",
            "subject": "math",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending"
    request_id = r.json()["request_id"]

    # درخواستی از مدرسه خارج از این ناحیه
    other_school = await outside_school()
    async with AsyncSessionLocal() as s:
        outside = EmploymentRequest(
            school_id=other_school,
            requested_by=schooladmin,
            employee_user_id=newteacher,
            full_name="معلم خارج از ناحیه",
            employment_type="official",
            organization="government",
            subject="math",
            status="pending",
        )
        s.add(outside)
        await s.commit()
        outside_id = outside.id

    r = await client.get("/district/employment-requests", headers=auth(dtok))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["district_id"] == 1
    assert {row["id"] for row in body["requests"]} == {request_id}

    # فیلتر وضعیت
    r = await client.get(
        "/district/employment-requests", headers=auth(dtok), params={"status": "pending"}
    )
    assert {row["id"] for row in r.json()["requests"]} == {request_id}

    # تصمیم از همان endpoint موجود /admin (حوزه ناحیه چک می‌شود)
    r = await client.post(
        f"/admin/employment-requests/{request_id}/decide",
        headers=auth(dtok),
        json={"approve": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"

    # درخواستِ خارج از ناحیه همچنان pending است ولی دیده نمی‌شود
    r = await client.get(
        "/district/employment-requests", headers=auth(dtok), params={"status": "pending"}
    )
    assert {row["id"] for row in r.json()["requests"]} == set()

    r = await client.get(
        "/district/employment-requests", headers=auth(dtok), params={"status": "approved"}
    )
    assert {row["id"] for row in r.json()["requests"]} == {request_id}

    # مدیر مدرسه به صندوق ناحیه دسترسی ندارد → 403
    r = await client.get("/district/employment-requests", headers=auth(stok))
    assert r.status_code == 403
