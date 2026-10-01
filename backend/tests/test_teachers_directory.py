"""آزمون‌های Feature A: فهرست معلمان برای انتخاب در استخدام
(GET /admin/teachers-directory) و ورودی جدید POST /admin/employment-requests
با teacher_user_id (اعتبارسنجی نقش، 409 شاغل‌بودن، مسیر auto_approved و
سازگاری عقب‌رو با employee_user_id)."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_daneshyar.db")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.db import AsyncSessionLocal, Base, engine
from app.main import app
from app.models.employment import EmploymentRequest
from app.models.org import Employee, SchoolAssignment, User
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


# ------------------------- فهرست معلمان -------------------------


@pytest.mark.anyio
async def test_teachers_directory_listing(client, seeded):
    """همه معلمان + تخصیص‌های فعال و subjects؛ گارد view_students/manage_employment."""
    stok = await login(client, "schooladmin")
    dtok = await login(client, "districtadmin")
    ttok = await login(client, "teacher1")
    sutok = await login(client, "student1")

    # بدون مجوز view_students/manage_employment → 403
    for tok in (ttok, sutok):
        r = await client.get("/admin/teachers-directory", headers=auth(tok))
        assert r.status_code == 403
    # بدون توکن → 401
    r = await client.get("/admin/teachers-directory")
    assert r.status_code == 401

    r = await client.get("/admin/teachers-directory", headers=auth(stok))
    assert r.status_code == 200, r.text
    data = r.json()
    rows = {row["username"]: row for row in data["teachers"]}
    assert data["total"] == len(rows)
    assert {"teacher1", "teacher2", "newteacher", "tutor1"} <= set(rows)

    # معلم شاغل در مدرسه ۱: تخصیص فعال + درس + غیرآزاد
    t1 = rows["teacher1"]
    assert {"user_id", "full_name", "username", "subjects", "active_assignments", "available"} <= set(t1)
    assert t1["user_id"] == await user_id("teacher1")
    assert t1["full_name"] == "آقای احمدی"
    assert t1["subjects"] == ["math"]
    assert t1["available"] is False
    (assign,) = t1["active_assignments"]
    assert assign["school_id"] == 1
    assert assign["school_name"] == "دبیرستان نمونه دانشیار"
    assert assign["role"] == "teacher"
    assert assign["subject"] == "math"

    # معلم بدون هیچ تخصیص فعال → آزاد برای استخدام
    newt = rows["newteacher"]
    assert newt["available"] is True
    assert newt["active_assignments"] == []
    assert newt["subjects"] == []
    assert newt["full_name"] == "خانم صادقی"

    # مدیر ناحیه هم فهرست را می‌بیند
    r = await client.get("/admin/teachers-directory", headers=auth(dtok))
    assert r.status_code == 200, r.text
    assert r.json()["total"] == data["total"]


# ------------------------- اعتبارسنجی درخواست استخدام -------------------------


@pytest.mark.anyio
async def test_employment_request_validation(client, seeded):
    """teacher_user_id: معلم شاغل → 409؛ غیرمعلم → 400؛ ناموجود → 404؛
    بدون شناسه → 400."""
    stok = await login(client, "schooladmin")

    # معلم هم‌اکنون در مدرسه ۱ شاغل است → 409
    r = await client.post(
        "/admin/employment-requests",
        headers=auth(stok),
        json={
            "school_id": 1,
            "teacher_user_id": await user_id("teacher1"),
            "employment_type": "contractual",
            "organization": "government",
            "subject": "math",
        },
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "این معلم هم‌اکنون در این مدرسه شاغل است"

    # کاربر با نقش غیرمعلم → 400
    r = await client.post(
        "/admin/employment-requests",
        headers=auth(stok),
        json={
            "school_id": 1,
            "teacher_user_id": await user_id("student1"),
            "employment_type": "contractual",
            "organization": "government",
            "subject": "math",
        },
    )
    assert r.status_code == 400, r.text

    # کاربر ناموجود → 404
    r = await client.post(
        "/admin/employment-requests",
        headers=auth(stok),
        json={
            "school_id": 1,
            "teacher_user_id": 99999,
            "employment_type": "contractual",
            "organization": "government",
        },
    )
    assert r.status_code == 404

    # بدون هیچ شناسه‌ای → 400
    r = await client.post(
        "/admin/employment-requests",
        headers=auth(stok),
        json={"school_id": 1, "employment_type": "contractual", "organization": "government"},
    )
    assert r.status_code == 400

    # مدرسه ناموجود → 404
    r = await client.post(
        "/admin/employment-requests",
        headers=auth(stok),
        json={
            "school_id": 999,
            "teacher_user_id": await user_id("newteacher"),
            "employment_type": "official",
        },
    )
    assert r.status_code == 404

    # هیچ درخواستی ثبت نشده است
    async with AsyncSessionLocal() as s:
        count = len((await s.execute(select(EmploymentRequest))).scalars().all())
        assert count == 0


@pytest.mark.anyio
async def test_employment_flows_and_list_rows(client, seeded):
    """مسیر auto_approved (public+official) و pending (contractual) با
    teacher_user_id + سازگاری عقب‌رو با employee_user_id؛ سطرهای فهرست
    school_name و teacher_user_id دارند."""
    stok = await login(client, "schooladmin")
    dtok = await login(client, "districtadmin")
    newteacher = await user_id("newteacher")
    tutor1 = await user_id("tutor1")

    # مسیر auto_approved: سیاست public/official تأیید ناحیه نمی‌خواهد
    r = await client.post(
        "/admin/employment-requests",
        headers=auth(stok),
        json={
            "school_id": 1,
            "teacher_user_id": newteacher,
            "employment_type": "official",
            "organization": "government",
            "subject": "math",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "auto_approved"

    # تأیید خودکار یعنی تخصیص فعالِ همان لحظه برای همان معلم ساخته شده
    async with AsyncSessionLocal() as s:
        employee = (
            await s.execute(select(Employee).where(Employee.user_id == newteacher))
        ).scalar_one()
        active = (
            await s.execute(
                select(SchoolAssignment).where(
                    SchoolAssignment.employee_id == employee.id,
                    SchoolAssignment.school_id == 1,
                    SchoolAssignment.status == "active",
                )
            )
        ).scalars().all()
        assert len(active) == 1
        assert active[0].subject == "math"

    # مسیر pending: سیاست public/contractual تأیید ناحیه می‌خواهد
    r = await client.post(
        "/admin/employment-requests",
        headers=auth(stok),
        json={
            "school_id": 1,
            "teacher_user_id": tutor1,
            "employment_type": "contractual",
            "organization": "government",
            "subject": "math",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending"

    # سازگاری عقب‌رو: employee_user_id بدون teacher_user_id هم کار می‌کند
    r = await client.post(
        "/admin/employment-requests",
        headers=auth(stok),
        json={
            "school_id": 1,
            "employee_user_id": tutor1,
            "full_name": "نام قدیمی نادیده گرفته می‌شود",
            "employment_type": "part_time",
            "organization": "government",
            "subject": "math",
        },
    )
    assert r.status_code == 200, r.text
    legacy_id = r.json()["request_id"]

    # سطرهای فهرست برای UI کافی هستند
    r = await client.get("/admin/employment-requests", headers=auth(dtok))
    assert r.status_code == 200, r.text
    rows = r.json()["requests"]
    assert len(rows) == 3
    for key in (
        "id",
        "full_name",
        "teacher_user_id",
        "employment_type",
        "subject",
        "organization",
        "status",
        "school_id",
        "school_name",
        "created_at",
    ):
        assert key in rows[0]
    by_id = {row["id"]: row for row in rows}
    auto_row = next(row for row in rows if row["status"] == "auto_approved")
    assert auto_row["teacher_user_id"] == newteacher
    assert auto_row["school_name"] == "دبیرستان نمونه دانشیار"
    assert auto_row["full_name"] == "خانم صادقی"  # از پروفایل کاربر، نه کلاینت
    assert by_id[legacy_id]["teacher_user_id"] == tutor1
    assert by_id[legacy_id]["employment_type"] == "part_time"
    # نامِ قدیمیِ ارسالی نادیده گرفته شد
    assert by_id[legacy_id]["full_name"] != "نام قدیمی نادیده گرفته می‌شود"

    # ردیف pending برای مدیر مدرسه هم دیده می‌شود
    r = await client.get("/admin/employment-requests", headers=auth(stok))
    assert {row["status"] for row in r.json()["requests"]} == {"auto_approved", "pending"}
