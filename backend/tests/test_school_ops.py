"""تست‌های پنل کامل مدیر مدرسه: شیفت‌ها، برنامه هفتگی، رکورد کلاس‌ها,
جابه‌جایی دانش‌آموز، کادر آموزشی و هماهنگی با پنل دانش‌آموز/معلم."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_schoolops.db")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.db import AsyncSessionLocal, Base, engine
from app.main import app
from app.models.rbac import AuditLog
from scripts.seed import seed

# شناسه‌های seed: schooladmin=1, districtadmin=2, teacher1=3, teacher2=4,
# student1=5 … student5=9, s2student1=15 (کلاس‌ها: ۱۰۱=1، ۱۰۲=2، ۲۰۱=3)


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


# ------------------------- شیفت‌ها -------------------------


@pytest.mark.anyio
async def test_seed_shifts_are_visible(client, seeded):
    """مدرسه ۱ تک‌شیفت و مدرسه ۲ دوشیفت — داده seed از endpoint خوانده می‌شود."""
    tok = await login(client, "schooladmin")
    r = await client.get("/admin/school/1/shifts", headers=auth(tok))
    assert r.status_code == 200
    shifts = r.json()["shifts"]
    assert len(shifts) == 1
    assert shifts[0]["start_time"] == "08:00" and shifts[0]["end_time"] == "15:00"

    r = await client.get("/admin/school/2/shifts", headers=auth(tok))
    assert r.status_code == 403  # دامنه: مدیر مدرسه ۱ فقط مدرسه خودش


@pytest.mark.anyio
async def test_district_admin_sees_double_shift(client, seeded):
    tok = await login(client, "districtadmin")
    r = await client.get("/admin/school/2/shifts", headers=auth(tok))
    assert r.status_code == 200
    shifts = r.json()["shifts"]
    assert [s["name"] for s in shifts] == ["شیفت اول", "شیفت دوم"]
    assert shifts[1]["end_time"] == "18:00"


@pytest.mark.anyio
async def test_put_shifts_validation(client, seeded):
    tok = await login(client, "schooladmin")

    # بدون شیفت
    r = await client.put("/admin/school/1/shifts", headers=auth(tok), json={"shifts": []})
    assert r.status_code == 400

    # تداخل ساعتی
    r = await client.put(
        "/admin/school/1/shifts",
        headers=auth(tok),
        json={"shifts": [
            {"name": "اول", "start_time": "08:00", "end_time": "13:00"},
            {"name": "دوم", "start_time": "12:00", "end_time": "18:00"},
        ]},
    )
    assert r.status_code == 400

    # ساعت نامعتبر
    r = await client.put(
        "/admin/school/1/shifts",
        headers=auth(tok),
        json={"shifts": [{"name": "صبح", "start_time": "25:00", "end_time": "26:00"}]},
    )
    assert r.status_code == 400

    # شروع بعد از پایان
    r = await client.put(
        "/admin/school/1/shifts",
        headers=auth(tok),
        json={"shifts": [{"name": "صبح", "start_time": "14:00", "end_time": "08:00"}]},
    )
    assert r.status_code == 400


@pytest.mark.anyio
async def test_put_shifts_conflicts_with_existing_schedule(client, seeded):
    """برنامه نمونه (تا ۱۴:۳۰) باید در شیفت جدید بگنجد وگرنه 400."""
    tok = await login(client, "schooladmin")
    r = await client.put(
        "/admin/school/1/shifts",
        headers=auth(tok),
        json={"shifts": [{"name": "فشرده", "start_time": "08:00", "end_time": "09:00"}]},
    )
    assert r.status_code == 400

    r = await client.put(
        "/admin/school/1/shifts",
        headers=auth(tok),
        json={"shifts": [{"name": "صبح", "start_time": "07:30", "end_time": "16:00"}]},
    )
    assert r.status_code == 200
    assert r.json()["shifts"][0]["start_time"] == "07:30"

    assert len(await audit_actions("school_shifts_updated")) >= 1


@pytest.mark.anyio
async def test_shifts_write_requires_permission(client, seeded):
    """دانش‌آموز و معلم اجازه نوشتن ندارند (403 پیش از بررسی وجود)."""
    for user in ("student1", "teacher1"):
        tok = await login(client, user)
        r = await client.put(
            "/admin/school/1/shifts",
            headers=auth(tok),
            json={"shifts": [{"name": "صبح", "start_time": "08:00", "end_time": "15:00"}]},
        )
        assert r.status_code == 403, user


# ------------------------- برنامه هفتگی -------------------------


@pytest.mark.anyio
async def test_school_schedule_grouped(client, seeded):
    tok = await login(client, "schooladmin")
    r = await client.get("/admin/school/1/schedule", headers=auth(tok))
    assert r.status_code == 200
    data = r.json()
    assert len(data["shifts"]) == 1
    by_name = {c["class_name"]: c for c in data["classes"]}
    assert "۱۰۱" in by_name and "۱۰۲" in by_name
    entries = by_name["۱۰۱"]["entries"]
    assert all(e["day_name"] for e in entries)
    assert any(e["teacher_name"] for e in entries)


@pytest.mark.anyio
async def test_put_class_schedule_ok_and_sync(client, seeded):
    """ثبت برنامه → هم در پنل مدیر و هم پنل دانش‌آموز/معلم دیده می‌شود."""
    tok = await login(client, "schooladmin")
    entries = [
        {"day": 0, "start_time": "08:00", "end_time": "09:30", "subject": "math", "teacher_user_id": 3},
        {"day": 1, "start_time": "09:45", "end_time": "11:15", "subject": "math", "teacher_user_id": 3},
        {"day": 2, "start_time": "12:00", "end_time": "13:00", "subject": "math", "teacher_user_id": None},
    ]
    r = await client.put(
        "/admin/classes/1/schedule", headers=auth(tok), json={"entries": entries}
    )
    assert r.status_code == 200, r.text
    assert len(r.json()["entries"]) == 3

    # هماهنگی: دانش‌آموز کلاس ۱ همان برنامه را می‌بیند
    stok = await login(client, "student1")
    r = await client.get("/student/schedule", headers=auth(stok))
    assert r.status_code == 200
    body = r.json()
    assert body["class_id"] == 1
    assert len(body["entries"]) == 3
    assert body["shifts"][0]["name"] == "شیفت صبح"

    # هماهنگی: معلم برنامه خودش را با نام کلاس می‌بیند
    ttok = await login(client, "teacher1")
    r = await client.get("/teacher/my-schedule", headers=auth(ttok))
    assert r.status_code == 200
    t = r.json()
    assert len(t["schools"]) == 1
    assert t["schools"][0]["my_shifts"] == ["شیفت صبح"]
    assert t["schools"][0]["entries"][0]["class_name"] == "۱۰۱"
    # دو جلسه ۱٫۵ ساعته با معلم teacher1 (جلسه سوم بدون معلم)
    assert t["schools"][0]["weekly_hours"] == 3.0

    assert len(await audit_actions("class_schedule_updated")) >= 1


@pytest.mark.anyio
async def test_put_class_schedule_validations(client, seeded):
    tok = await login(client, "schooladmin")

    # روز نامعتبر
    r = await client.put(
        "/admin/classes/1/schedule",
        headers=auth(tok),
        json={"entries": [{"day": 9, "start_time": "08:00", "end_time": "09:00", "subject": "math"}]},
    )
    assert r.status_code == 400

    # خارج از شیفت (مدرسه ۱: ۰۸:۰۰–۱۵:۰۰)
    r = await client.put(
        "/admin/classes/1/schedule",
        headers=auth(tok),
        json={"entries": [{"day": 0, "start_time": "16:00", "end_time": "17:00", "subject": "math"}]},
    )
    assert r.status_code == 400

    # تداخل داخل کلاس
    r = await client.put(
        "/admin/classes/1/schedule",
        headers=auth(tok),
        json={"entries": [
            {"day": 0, "start_time": "08:00", "end_time": "10:00", "subject": "math"},
            {"day": 0, "start_time": "09:00", "end_time": "11:00", "subject": "math"},
        ]},
    )
    assert r.status_code == 400

    # معلم نبودن کاربر (student1 معلم نیست)
    r = await client.put(
        "/admin/classes/1/schedule",
        headers=auth(tok),
        json={"entries": [
            {"day": 0, "start_time": "08:00", "end_time": "09:00", "subject": "math", "teacher_user_id": 5},
        ]},
    )
    assert r.status_code == 400

    # بدون درس
    r = await client.put(
        "/admin/classes/1/schedule",
        headers=auth(tok),
        json={"entries": [{"day": 0, "start_time": "08:00", "end_time": "09:00", "subject": ""}]},
    )
    assert r.status_code == 400


@pytest.mark.anyio
async def test_teacher_double_booking_rejected(client, seeded):
    """teacher2 ساعت ۱۱:۰۰–۱۲:۳۰ شنبه در کلاس ۱۰۲ هست؛ کلاس ۱۰۱ نباید همزمان از او ثبت کند."""
    tok = await login(client, "schooladmin")
    r = await client.put(
        "/admin/classes/1/schedule",
        headers=auth(tok),
        json={"entries": [
            {"day": 0, "start_time": "11:00", "end_time": "12:30", "subject": "math", "teacher_user_id": 4},
        ]},
    )
    assert r.status_code == 400
    assert "کلاس" in r.json()["detail"]


@pytest.mark.anyio
async def test_class_schedule_guards(client, seeded):
    # دانش‌آموز/معلم نمی‌نویسند
    for user in ("student1", "teacher1"):
        tok = await login(client, user)
        r = await client.put(
            "/admin/classes/1/schedule",
            headers=auth(tok),
            json={"entries": []},
        )
        assert r.status_code == 403, user

    # دامنه: مدیر مدرسه ۱ به کلاس مدرسه ۲ دسترسی ندارد
    tok = await login(client, "schooladmin")
    r = await client.get("/admin/classes/3/schedule", headers=auth(tok))
    assert r.status_code == 403
    r = await client.put("/admin/classes/3/schedule", headers=auth(tok), json={"entries": []})
    assert r.status_code == 403

    # شناسه ناشناخته هم 403 (گارد دامنه پیش از بررسی وجود)
    r = await client.get("/admin/classes/9999/schedule", headers=auth(tok))
    assert r.status_code == 403


# ------------------------- رکورد کلاس‌ها و جابه‌جایی دانش‌آموز -------------------------


@pytest.mark.anyio
async def test_roster_groups_students_by_class(client, seeded):
    tok = await login(client, "schooladmin")
    r = await client.get("/admin/school/1/roster", headers=auth(tok))
    assert r.status_code == 200
    data = r.json()
    assert data["total_students"] == 5
    by_name = {c["name"]: c for c in data["classes"]}
    assert by_name["۱۰۱"]["students_count"] == 3
    assert by_name["۱۰۲"]["students_count"] == 2
    assert all(s["full_name"] for c in data["classes"] for s in c["students"])
    # مدرسه ۲ دانش‌آموزان خودش را ندارد (دامنه‌مندی)
    assert all(s["class_id"] in (1, 2) for c in data["classes"] for s in c["students"])


@pytest.mark.anyio
async def test_move_student_between_classes(client, seeded):
    tok = await login(client, "schooladmin")

    # انتقال student5 (کلاس ۱۰۲) به کلاس ۱۰۱
    r = await client.patch(
        "/admin/school/1/students/9",
        headers=auth(tok),
        json={"class_id": 1},
    )
    assert r.status_code == 200, r.text
    assert r.json()["class_id"] == 1

    # همان‌جا در رکورد دیده می‌شود
    r = await client.get("/admin/school/1/roster", headers=auth(tok))
    by_name = {c["name"]: c for c in r.json()["classes"]}
    assert by_name["۱۰۱"]["students_count"] == 4
    assert by_name["۱۰۲"]["students_count"] == 1

    # پنل دانش‌آموز هم فوراً هماهنگ شد
    stok = await login(client, "student5")
    r = await client.get("/student/schedule", headers=auth(stok))
    assert r.json()["class_id"] == 1

    assert len(await audit_actions("student_class_moved")) >= 1


@pytest.mark.anyio
async def test_move_student_validation(client, seeded):
    tok = await login(client, "schooladmin")

    # کلاس مدرسه دیگر
    r = await client.patch(
        "/admin/school/1/students/5", headers=auth(tok), json={"class_id": 3}
    )
    assert r.status_code == 400

    # دانش‌آموز مدرسه دیگر
    r = await client.patch(
        "/admin/school/1/students/15", headers=auth(tok), json={"class_id": 1}
    )
    assert r.status_code == 404

    # ظرفیت تکمیل (کلاس ۱۰۲ پر است)
    async with AsyncSessionLocal() as s:
        from app.models.org import ClassRoom

        cls = await s.get(ClassRoom, 2)
        cls.capacity = 2
        await s.commit()
    r = await client.patch(
        "/admin/school/1/students/5", headers=auth(tok), json={"class_id": 2}
    )
    assert r.status_code == 409


@pytest.mark.anyio
async def test_create_and_patch_class(client, seeded):
    tok = await login(client, "schooladmin")

    r = await client.post(
        "/admin/school/1/classes",
        headers=auth(tok),
        json={"name": "۱۰۳", "grade": "grade_10", "capacity": 25},
    )
    assert r.status_code == 200, r.text
    new_id = r.json()["class"]["id"]

    # نام تکراری
    r = await client.post(
        "/admin/school/1/classes",
        headers=auth(tok),
        json={"name": "۱۰۳", "grade": "grade_10"},
    )
    assert r.status_code == 409

    # ویرایش ظرفیت
    r = await client.patch(f"/admin/classes/{new_id}", headers=auth(tok), json={"capacity": 20})
    assert r.status_code == 200
    assert r.json()["class"]["capacity"] == 20

    # ظرفیت کمتر از ثبت‌شده
    r = await client.patch("/admin/classes/2", headers=auth(tok), json={"capacity": 1})
    assert r.status_code == 409

    assert len(await audit_actions("class_created")) >= 1


# ------------------------- کادر آموزشی و شیفت معلمان -------------------------


@pytest.mark.anyio
async def test_staff_shows_shifts_and_hours(client, seeded):
    tok = await login(client, "schooladmin")
    r = await client.get("/admin/school/1/staff", headers=auth(tok))
    assert r.status_code == 200
    data = r.json()
    by_name = {t["full_name"]: t for t in data["teachers"]}
    # teacher1 (آقای احمدی): ۵ جلسه × ۱٫۵ ساعت = ۷٫۵ ساعت در شیفت صبح
    t1 = by_name["آقای احمدی"]
    assert t1["shifts"] == ["شیفت صبح"]
    assert t1["weekly_hours"] == 7.5
    assert t1["classes"] == ["۱۰۱"] and t1["subjects"] == ["math"]
    # teacher2 (خانم کریمی): ۳ جلسه = ۴٫۵ ساعت
    t2 = by_name["خانم کریمی"]
    assert t2["shifts"] == ["شیفت صبح"]
    assert t2["weekly_hours"] == 4.5
    assert t2["classes"] == ["۱۰۲"]
    # فقط کادر آموزشی (مدیر مدرسه در فهرست نیست)
    assert "مدیر مدرسه" not in by_name


@pytest.mark.anyio
async def test_staff_requires_permission(client, seeded):
    tok = await login(client, "student1")
    r = await client.get("/admin/school/1/staff", headers=auth(tok))
    assert r.status_code == 403


@pytest.mark.anyio
async def test_assign_and_unassign_teacher(client, seeded):
    tok = await login(client, "schooladmin")

    # تخصیص teacher1 به کلاس ۱۰۲ (درس جدید)
    r = await client.post(
        "/admin/classes/2/teachers",
        headers=auth(tok),
        json={"teacher_user_id": 3, "subject": "physics"},
    )
    assert r.status_code == 200, r.text
    assignment_id = r.json()["assignment"]["id"]

    # فهرست معلمان کلاس (برای نمایش/حذف در پنل)
    r = await client.get("/admin/classes/2/teachers", headers=auth(tok))
    assert r.status_code == 200
    listed = {t["assignment_id"]: t for t in r.json()["teachers"]}
    assert listed[assignment_id]["teacher_user_id"] == 3
    assert listed[assignment_id]["full_name"] == "آقای احمدی"

    # تکراری
    r = await client.post(
        "/admin/classes/2/teachers",
        headers=auth(tok),
        json={"teacher_user_id": 3, "subject": "physics"},
    )
    assert r.status_code == 409

    # غیرمعلم
    r = await client.post(
        "/admin/classes/2/teachers",
        headers=auth(tok),
        json={"teacher_user_id": 5, "subject": "math"},
    )
    assert r.status_code == 400

    # خاتمه تخصیص بدون جلسه فعال
    r = await client.delete(
        f"/admin/classes/2/teachers/{assignment_id}", headers=auth(tok)
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # تخصیص فعالِ دارای جلسه در برنامه (teacher1 در کلاس ۱۰۱) → 409
    async with AsyncSessionLocal() as s:
        from app.models.org import ClassTeacherAssignment

        row = (
            await s.execute(
                select(ClassTeacherAssignment).where(
                    ClassTeacherAssignment.class_id == 1,
                    ClassTeacherAssignment.teacher_user_id == 3,
                )
            )
        ).scalars().first()
        assignment_id = row.id
    r = await client.delete(f"/admin/classes/1/teachers/{assignment_id}", headers=auth(tok))
    assert r.status_code == 409


@pytest.mark.anyio
async def test_scope_isolation_unknown_school(client, seeded):
    """گارد دامنه پیش از بررسی وجود: مدرسه ناشناخته → 403."""
    tok = await login(client, "schooladmin")
    for path in (
        "/admin/school/9999/shifts",
        "/admin/school/9999/roster",
        "/admin/school/9999/staff",
        "/admin/school/9999/schedule",
    ):
        r = await client.get(path, headers=auth(tok))
        assert r.status_code == 403, path
