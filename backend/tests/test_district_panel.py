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


# ------------------------- §5–§6 مقایسه و رشد مدارس -------------------------


@pytest.mark.anyio
async def test_school_comparison_and_growth_three_stages(client, seeded):
    """§5: سه گام «سطح ورودی ← وضعیت فعلی ← میزان رشد» + سرکوب حداقل جمعیت؛
    §6: وضعیت فعلی و رشد دو شاخص متفاوت‌اند."""
    dtok = await login(client, "districtadmin")
    stok = await login(client, "schooladmin")

    r = await client.get("/district/schools/compare", headers=auth(dtok))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["district_id"] == 1
    assert body["stages"] == ["سطح ورودی", "وضعیت فعلی", "میزان رشد"]
    assert body["min_group"] == 10
    assert len(body["rows"]) == 2
    assert {row["school_code"] for row in body["rows"]} == {"S-1001", "S-1002"}
    for row in body["rows"]:
        for key in (
            "entry_mastery",
            "current_mastery",
            "growth",
            "exam_avg",
            "practice_completion_pct",
            "needs_intervention_pct",
        ):
            assert key in row
    # زیر حداقل جمعیت ⇒ هیچ عدد آموزشی نمایش داده نمی‌شود
    small = next(row for row in body["rows"] if row["school_code"] == "S-1001")
    big = next(row for row in body["rows"] if row["school_code"] == "S-1002")
    assert small["suppressed"] is True and small["current_mastery"] is None
    assert big["suppressed"] is False
    assert body["note_fa"] and "رشد" in body["note_fa"]

    # فیلتر پایه/درس پذیرفته می‌شود
    r = await client.get(
        "/district/schools/compare", headers=auth(dtok), params={"grade": "grade_10"}
    )
    assert r.status_code == 200 and r.json()["grade"] == "grade_10"

    # §6
    r = await client.get("/district/schools/growth", headers=auth(dtok))
    assert r.status_code == 200, r.text
    growth = r.json()
    assert growth["district_id"] == 1
    assert {"entry", "current", "growth", "series"} <= set(growth["district"])
    assert len(growth["rows"]) == 2
    for row in growth["rows"]:
        assert {"school_id", "suppressed", "entry", "current", "growth", "trend"} <= set(row)
    assert growth["note_fa"] and "دو شاخص متفاوت" in growth["note_fa"]

    # بدون حوزه ناحیه → 403
    r = await client.get("/district/schools/compare", headers=auth(stok))
    assert r.status_code == 403
    r = await client.get("/district/schools/growth", headers=auth(stok))
    assert r.status_code == 403


# ------------------------- §2/§3 روندها و شش محور سلامت -------------------------


@pytest.mark.anyio
async def test_trends_and_health_axes_are_separate(client, seeded):
    """§2 روندها + §3 شش محور مستقل — بدون هیچ «عدد سلامت» ساختگی واحد."""
    dtok = await login(client, "districtadmin")
    stok = await login(client, "schooladmin")

    r = await client.get("/district/trends", headers=auth(dtok))
    assert r.status_code == 200, r.text
    trends = r.json()
    keys = {t["key"] for t in trends["trends"]}
    assert {
        "exam_growth",
        "period_growth",
        "mastery_trend",
        "retention_trend",
        "engagement",
        "completion",
        "intervention",
        "exams",
    } <= keys
    for t in trends["trends"]:
        assert {"key", "title_fa", "value", "unit", "direction", "band", "note_fa"} <= set(t)
        assert t["band"] in ("good", "medium", "weak", "unknown")
    assert trends["min_group"] == 10
    assert "score" not in trends and "health_score" not in trends

    r = await client.get("/district/health", headers=auth(dtok))
    assert r.status_code == 200, r.text
    health = r.json()
    axes = {a["key"]: a for a in health["axes"]}
    assert set(axes) == {"learning", "mastery", "retention", "assessment", "engagement", "intervention"}
    for a in health["axes"]:
        assert a["question_fa"] and a["title_fa"] and a["detail_fa"]
        assert a["suppressed"] in (True, False)
    assert "overall" not in health and "score" not in health
    assert health["note_fa"] and "تک عدد" not in health["note_fa"]

    # بدون حوزه ناحیه → 403
    for path in ("/district/trends", "/district/health"):
        r = await client.get(path, headers=auth(stok))
        assert r.status_code == 403


# ------------------------- §9/§11/§29/§30 مرکز توجه -------------------------


@pytest.mark.anyio
async def test_attention_center_flags_and_suppression(client, seeded):
    """مرکز توجه: پرچم‌ها «هشدار» هستند نه اتهام؛ اعداد زیر حداقل جمعیت
    سرکوب می‌شوند و همه متن‌ها فارسی است."""
    dtok = await login(client, "districtadmin")
    stok = await login(client, "schooladmin")

    r = await client.get("/district/attention-center", headers=auth(dtok))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["district_id"] == 1
    assert len(body["schools"]) == 2
    assert {"critical", "attention", "forming", "normal", "positive"} == set(body["severity_counts"])
    assert "thresholds" in body and "problems" in body and "alerts" in body

    for row in body["schools"]:
        assert row["kind"] == "school"
        assert row["severity_fa"]
        assert isinstance(row["flags"], list)
        for flag in row["flags"]:
            assert flag["severity"] in ("critical", "attention", "forming", "positive")
            assert flag["title_fa"] and flag["detail_fa"]
    for row in body["classes"]:
        assert row["kind"] == "class"
        assert row["severity_fa"]
    for alert in body["alerts"]:
        assert alert["level_fa"] and alert["title_fa"] and alert["message_fa"]
    assert body["note_fa"] and "حداقل جمعیت" in body["note_fa"]

    # بدون حوزه ناحیه → 403
    r = await client.get("/district/attention-center", headers=auth(stok))
    assert r.status_code == 403


# ------------------------- §7/§8/§23 تحلیل خطای ناحیه -------------------------


@pytest.mark.anyio
async def test_district_error_analysis_groups_causes(client, seeded):
    """تحلیل خطای ناحیه: سهم هر علت + تفکیک مدرسه + مباحث پرتکرار (§23)."""
    dtok = await login(client, "districtadmin")
    stok = await login(client, "schooladmin")

    r = await client.get("/district/error-analysis", headers=auth(dtok))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["district_id"] == 1
    for key in ("total", "students", "suppressed", "min_group", "causes", "schools", "topics"):
        assert key in body
    for c in body["causes"]:
        assert {"key", "title_fa", "count", "pct"} <= set(c)
        assert c["title_fa"]
    assert len(body["schools"]) == 2
    assert {row["name"] for row in body["schools"]} if body["schools"] else True
    assert body["note_fa"]

    # بدون حوزه ناحیه → 403
    r = await client.get("/district/error-analysis", headers=auth(stok))
    assert r.status_code == 403


# ------------------------- §18–§19 انتقال دانش‌آموز -------------------------


@pytest.mark.anyio
async def test_student_transfer_moves_profile_and_audits(client, seeded):
    """§19: انتقال با دلیل + تأییدکننده، حفظ سابقه، جابه‌جایی پروفایل و
    ممیزی student_transferred — هیچ داده‌ای حذف نمی‌شود."""
    dtok = await login(client, "districtadmin")
    stok = await login(client, "schooladmin")

    async with AsyncSessionLocal() as s:
        student = (
            await s.execute(select(User).where(User.username == "s2student1"))
        ).scalar_one()
        sid = student.id

    # دلیل خالی → 400
    r = await client.post(
        "/district/transfers", headers=auth(dtok),
        json={"student_user_id": sid, "to_school_id": 1, "reason_fa": "   "},
    )
    assert r.status_code == 400

    # مدرسه مقصد خارج از ناحیه → 404
    other_id = await outside_school()
    r = await client.post(
        "/district/transfers", headers=auth(dtok),
        json={"student_user_id": sid, "to_school_id": other_id, "reason_fa": "نقل‌وانتقال"},
    )
    assert r.status_code == 404

    # دانش‌آموز ناموجود → 404
    r = await client.post(
        "/district/transfers", headers=auth(dtok),
        json={"student_user_id": 999999, "to_school_id": 1, "reason_fa": "نقل‌وانتقال"},
    )
    assert r.status_code == 404

    # انتقال موفق: مدرسه ۲ ← مدرسه ۱
    r = await client.post(
        "/district/transfers", headers=auth(dtok),
        json={"student_user_id": sid, "to_school_id": 1, "reason_fa": "نقل‌وانتقال خانوادگی"},
    )
    assert r.status_code == 200, r.text
    t = r.json()["transfer"]
    assert t["from_school_id"] == 2 and t["to_school_id"] == 1
    assert t["reason_fa"] == "نقل‌وانتقال خانوادگی"
    assert t["status"] == "approved"
    assert t["from_class_id"] is not None and t["to_class_id"] is not None

    # پروفایل جابه‌جا شده و کلاس مقصد هم‌پایه است
    async with AsyncSessionLocal() as s:
        from app.models.org import StudentProfile

        profile = (
            await s.execute(select(StudentProfile).where(StudentProfile.user_id == sid))
        ).scalar_one()
        assert profile.school_id == 1
        assert profile.class_id == t["to_class_id"]

    # ممیزی
    transferred = await audit_rows("student_transferred")
    assert len(transferred) == 1
    assert transferred[0][0] == await user_id("districtadmin")
    assert "to_school=1" in (transferred[0][1] or "")

    # انتقال به همان مدرسه → 400
    r = await client.post(
        "/district/transfers", headers=auth(dtok),
        json={"student_user_id": sid, "to_school_id": 1, "reason_fa": "تکراری"},
    )
    assert r.status_code == 400

    # سابقه انتقال‌ها
    r = await client.get("/district/transfers", headers=auth(dtok))
    assert r.status_code == 200, r.text
    rows = r.json()["transfers"]
    assert r.json()["total"] == 1
    assert rows[0]["student_user_id"] == sid
    assert rows[0]["from_school"] and rows[0]["to_school"]

    # مدیر مدرسه اجازه انتقال ندارد → 403
    r = await client.post(
        "/district/transfers", headers=auth(stok),
        json={"student_user_id": sid, "to_school_id": 1, "reason_fa": "بدون مجوز"},
    )
    assert r.status_code == 403


# ------------------------- §31–§32 گزارش ناحیه و ارسال به استان -------------------------


@pytest.mark.anyio
async def test_district_report_lifecycle_to_province(client, seeded):
    """§31 تولید پیش‌نویس گزارش + §32 ارسال به استان و تصمیم استان
    (برگشت/تأیید) — با ممیزی کامل."""
    dtok = await login(client, "districtadmin")
    ptok = await login(client, "provinceadmin")
    stok = await login(client, "schooladmin")
    period = {"period_start": "2026-01-01", "period_end": "2026-03-31"}

    # عنوان خالی → 400
    r = await client.post(
        "/district/reports/generate", headers=auth(dtok),
        json={**period, "title_fa": "  "},
    )
    assert r.status_code == 400

    # بازه نامعتبر → 400
    r = await client.post(
        "/district/reports/generate", headers=auth(dtok),
        json={"period_start": "2026-03-31", "period_end": "2026-01-01", "title_fa": "ناعتبر"},
    )
    assert r.status_code == 400

    # تولید پیش‌نویس
    r = await client.post(
        "/district/reports/generate", headers=auth(dtok),
        json={**period, "title_fa": "گزارش فصل زمستان ناحیه ۱"},
    )
    assert r.status_code == 200, r.text
    report = r.json()["report"]
    rid = report["id"]
    assert report["status"] == "draft" and report["status_fa"] == "پیش‌نویس"
    generated = await audit_rows("district_report_generated")
    assert len(generated) == 1 and generated[0][0] == await user_id("districtadmin")

    # فهرست + جزئیات با payload تجمیعی
    r = await client.get("/district/reports", headers=auth(dtok))
    assert r.status_code == 200 and r.json()["total"] == 1
    r = await client.get(f"/district/reports/{rid}", headers=auth(dtok))
    assert r.status_code == 200, r.text
    payload = r.json()["report"]["payload"]
    assert payload["summary"]["schools_count"] == 2
    assert payload["period"] == {"start": "2026-01-01", "end": "2026-03-31"}
    assert "schools" in payload and "health_axes" in payload and "attention" in payload
    assert payload["note_fa"]

    # ارسال به استان
    r = await client.post(f"/district/reports/{rid}/submit", headers=auth(dtok))
    assert r.status_code == 200, r.text
    assert r.json()["report"]["status"] == "submitted"
    submitted = await audit_rows("province_report_submitted")
    assert len(submitted) == 1 and submitted[0][0] == await user_id("districtadmin")

    # ارسال دوباره → 409
    r = await client.post(f"/district/reports/{rid}/submit", headers=auth(dtok))
    assert r.status_code == 409

    # مدیر مدرسه به گزارش‌ها دسترسی ندارد → 403
    r = await client.get("/district/reports", headers=auth(stok))
    assert r.status_code == 403

    # ---- سمت استان ----
    r = await client.get("/geo/province/1/district-reports", headers=auth(ptok))
    assert r.status_code == 200, r.text
    rows = r.json()["reports"]
    assert r.json()["total"] == 1
    assert rows[0]["id"] == rid and rows[0]["district_name"] == "ناحیه ۱ تهران"
    assert rows[0]["status"] == "submitted"

    # برگشت بدون دلیل → 400
    r = await client.post(
        f"/geo/province/1/district-reports/{rid}/decision", headers=auth(ptok),
        json={"decision": "return"},
    )
    assert r.status_code == 400

    # برگشت برای اصلاح
    r = await client.post(
        f"/geo/province/1/district-reports/{rid}/decision", headers=auth(ptok),
        json={"decision": "return", "note_fa": "بخش مداخله‌ها تکمیل شود"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["report"]["status"] == "returned"
    assert r.json()["report"]["review_note"] == "بخش مداخله‌ها تکمیل شود"
    returned = await audit_rows("province_report_returned")
    assert len(returned) == 1 and returned[0][0] == await user_id("provinceadmin")

    # گزارش برگشتی دوباره قابل ارسال است
    r = await client.post(f"/district/reports/{rid}/submit", headers=auth(dtok))
    assert r.status_code == 200 and r.json()["report"]["status"] == "submitted"

    # تأیید نهایی
    r = await client.post(
        f"/geo/province/1/district-reports/{rid}/decision", headers=auth(ptok),
        json={"decision": "approve"},
    )
    assert r.status_code == 200 and r.json()["report"]["status"] == "approved"
    approved = await audit_rows("province_report_approved")
    assert len(approved) == 1

    # استانِ دیگر/کسی بدون مجوز استان → 403 یا 404
    r = await client.get("/geo/province/1/district-reports", headers=auth(stok))
    assert r.status_code == 403
    # ناحیه نمی‌تواند تصمیم استان بگیرد
    r = await client.post(
        f"/geo/province/1/district-reports/{rid}/decision", headers=auth(dtok),
        json={"decision": "approve"},
    )
    assert r.status_code == 403
