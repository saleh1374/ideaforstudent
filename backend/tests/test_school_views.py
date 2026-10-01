"""تست‌های §8 مقایسه معلم با معلم و §13 نمای فردی دانش‌آموز (پنل مدیر مدرسه)."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_schoolviews.db")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.db import AsyncSessionLocal, Base, engine
from app.main import app
from app.models.org import StudentProfile, User
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


# ------------------------- §8 مقایسه معلم با معلم -------------------------


@pytest.mark.anyio
async def test_teacher_comparison_shape_and_suppression(client, seeded):
    tok = await login(client, "schooladmin")
    r = await client.get("/admin/school/1/teachers-compare?subject=math", headers=auth(tok))
    assert r.status_code == 200, r.text
    data = r.json()

    assert data["subject"] == "math"
    assert data["min_group"] >= 1
    assert data["raw_score_note_fa"] and data["weighting_note_fa"] and data["min_group_note"]

    # هر دو کلاس ریاضی (۱۰۱ و ۱۰۲) با معلم خودشان
    rows = data["rows"]
    assert len(rows) == 2
    by_class = {row["class_name"]: row for row in rows}
    assert set(by_class) == {"۱۰۱", "۱۰۲"}
    assert by_class["۱۰۱"]["teacher_name"] == "آقای احمدی"
    assert by_class["۱۰۲"]["teacher_name"] == "خانم کریمی"

    for row in rows:
        # عوامل زمینه‌ای §8 همیشه کامل‌اند — حضور عمداً null + توضیح
        ctx = row["context"]
        for key in (
            "baseline_mastery",
            "students_count",
            "attendance_pct",
            "exam_difficulty_avg",
            "prereq_weak_ratio",
            "sessions_recorded",
            "practice_evidence",
            "plan_completion_pct",
        ):
            assert key in ctx, key
        assert ctx["attendance_pct"] is None
        assert ctx["attendance_note_fa"]
        assert set(ctx["factor_labels_fa"]) >= {
            "baseline_mastery",
            "attendance_pct",
            "exam_difficulty_avg",
        }

        # سرکوب حداقل جمعیت: زیر حد → هیچ عددی از تسط/رشد/ماندگاری نمی‌آید
        if row["suppressed"]:
            assert row["students_with_data"] < data["min_group"]
            assert row["mastery"] is None
            assert row["retention"] is None
            assert row["growth"] is None
        else:
            assert row["students_with_data"] >= data["min_group"]
            assert row["mastery"] is not None

    # تجمیع در سطح معلم، بدون امتیاز کلی
    teachers = data["teachers"]
    assert {t["teacher_name"] for t in teachers} == {"آقای احمدی", "خانم کریمی"}
    for t in teachers:
        assert "score" not in t
        assert t["classes_count"] >= 1
        assert isinstance(t["suppressed"], bool)

    visible = [row for row in rows if not row["suppressed"]]
    assert data["comparison_valid"] == (len(visible) >= 2)


@pytest.mark.anyio
async def test_teacher_comparison_guards(client, seeded):
    # دانش‌آموز: بدون view_school_analytics → 403
    tok = await login(client, "student1")
    r = await client.get("/admin/school/1/teachers-compare", headers=auth(tok))
    assert r.status_code == 403

    # مدیر مدرسه: مدرسه ناشناس → گارد Scope پیش از چک وجود اجرا می‌شود (۴۰۳)
    tok = await login(client, "schooladmin")
    r = await client.get("/admin/school/999/teachers-compare", headers=auth(tok))
    assert r.status_code == 403

    # بدون توکن → 401
    r = await client.get("/admin/school/1/teachers-compare")
    assert r.status_code == 401


# ------------------------- §13 نمای فردی دانش‌آموز -------------------------


@pytest.mark.anyio
async def test_school_students_list_and_detail(client, seeded):
    tok = await login(client, "schooladmin")

    # فهرست دانش‌آموزان مدرسه (انتخابگر)
    r = await client.get("/admin/school/1/students", headers=auth(tok))
    assert r.status_code == 200, r.text
    listing = r.json()
    assert listing["total"] == 5  # ۳ نفر کلاس ۱۰۱ + ۲ نفر کلاس ۱۰۲
    for row in listing["students"]:
        assert row["user_id"] and row["full_name"] and row["class_name"]

    sid = await user_id("student1")
    r = await client.get(f"/admin/school/1/students/{sid}", headers=auth(tok))
    assert r.status_code == 200, r.text
    d = r.json()

    # هسته نمای فردی طبق شکل §13
    assert d["student"]["user_id"] == sid
    assert d["student"]["class_name"] == "۱۰۱"
    m = d["mastery"]
    assert m["rank_in_class"] is None or 1 <= m["rank_in_class"] <= (m["class_size"] or 0)
    assert m["trend"] in {"up", "down", "flat", "unknown"}
    assert isinstance(m["overall"], (float, int)) or m["overall"] is None
    assert isinstance(m["retention"], (float, int)) or m["retention"] is None

    ind = d["indicators"]
    assert isinstance(ind["repeat_open_errors"], int)
    assert isinstance(ind["critical_topics"], int)
    assert ind["attendance_pct"] is None and ind["attendance_note_fa"]
    assert "exam_sessions_recorded" in ind["platform"]

    # مشکل اصلی + چرخه مداخله (§13)
    assert d["main_problem_fa"]
    assert set(d["interventions"]) == {"cycles", "resolved", "relapsed", "result_fa"}
    assert d["interventions"]["result_fa"]
    # بدون رتبه در هیچ برد عمومی — فقط توضیح داخلی
    assert "برد عمومی" in d["note_fa"]

    assert isinstance(d["topics"], list)
    assert isinstance(d["recent_attempts"], list)
    for topic in d["topics"]:
        assert topic["status"] in {"mastered", "consolidating", "weak", "critical", "unknown"}


@pytest.mark.anyio
async def test_student_detail_guards(client, seeded):
    # دانش‌آموز دیگر مدرسه (مدرسه ۲) داخل مدرسه ۱ نیست → 404
    foreign = await user_id("s2student1")
    tok = await login(client, "schooladmin")
    r = await client.get(f"/admin/school/1/students/{foreign}", headers=auth(tok))
    assert r.status_code == 404

    # دانش‌آموز خودش دسترسی view_students ندارد → 403
    stok = await login(client, "student1")
    r = await client.get(f"/admin/school/1/students/{foreign}", headers=auth(stok))
    assert r.status_code == 403

    # فهرست دانش‌آموزان هم حوزه‌مند است
    r = await client.get("/admin/school/1/students", headers=auth(stok))
    assert r.status_code == 403

    # مدیر ناحیه (حوزه district → پوشش مدرسه) مجاز است
    dtok = await login(client, "districtadmin")
    r = await client.get("/admin/school/1/students", headers=auth(dtok))
    assert r.status_code == 200, r.text

    # مدرسه ناشناس → گارد Scope پیش از چک وجود اجرا می‌شود (۴۰۳)
    r = await client.get("/admin/school/999/students", headers=auth(tok))
    assert r.status_code == 403
